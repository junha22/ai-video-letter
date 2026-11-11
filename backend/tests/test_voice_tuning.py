"""Worker side of optional voice tuning: basic registration trains only when chosen, training keeps the
registered reference sentence even after more recordings, and every training result is announced."""

import unittest
from unittest.mock import patch

import numpy as np
from sqlalchemy import select

from _test_support import TEST_ROOT, db, settings
from app import worker
from app.models import Job, Notification, User, VoiceProfile, VoiceSample
from app.services import audio, s3gen, storage

LEGACY_SENTENCES = [
    {"kind": "statement", "text": "보내 주신 반찬을 맛있게 먹었어요."},
    {"kind": "calm", "text": "오늘은 집 근처를 천천히 걸었어요."},
] + [{"kind": "question", "text": f"테스트 문장 {i}"} for i in range(2, 12)]


class VoiceTuningWorkerTests(unittest.TestCase):
    def setUp(self):
        self.assertEqual(settings.data_dir, TEST_ROOT)
        db.Base.metadata.drop_all(db.engine)
        db.init_db()
        for name, value in (("tts_provider", "wemeet"), ("s3gen_training", True), ("s3gen_remote_url", "http://gpu.test/train")):
            p = patch.object(settings, name, value)
            p.start()
            self.addCleanup(p.stop)
        for name, value in (("register_voice", {"speech_seconds": 6.0}), ("set_s3gen_adapter", None)):
            p = patch.object(worker.wemeet_tts, name, return_value=value)
            p.start()
            self.addCleanup(p.stop)
        p = patch.object(worker.s3gen, "delete_candidate", return_value=True)
        p.start()
        self.addCleanup(p.stop)
        with db.SessionLocal() as session:
            user = User(name="voice tuning test")
            session.add(user)
            session.flush()
            self.uid = user.id
            session.add(VoiceProfile(user_id=user.id, sentences=LEGACY_SENTENCES, status="processing"))
            session.commit()
        self.session = db.SessionLocal()
        self.addCleanup(self.session.close)

    def add_sample(self, index, seconds, snr=30.0):
        path = storage.user_dir(self.uid, "voice") / f"sample_{index:02d}.wav"
        rng = np.random.default_rng(index)
        audio.write_wav(path, (0.1 * rng.standard_normal(int(seconds * audio.SAMPLE_RATE))).astype(np.float32))
        self.session.add(VoiceSample(user_id=self.uid, index=index, text=LEGACY_SENTENCES[index]["text"],
                                     path=storage.rel_path(path), duration=seconds, speech_db=-20, snr_db=snr, ok=True))
        self.session.commit()

    def profile(self):
        self.session.expire_all()
        return self.session.scalar(select(VoiceProfile).where(VoiceProfile.user_id == self.uid))

    def queued(self, type):
        return self.session.scalars(select(Job).where(Job.type == type, Job.status == "queued")).all()

    def notices(self):
        return self.session.scalars(select(Notification).where(Notification.user_id == self.uid).order_by(Notification.id)).all()

    def register(self, tune):
        job = Job(type="voice", user_id=self.uid, payload={"tune": tune})
        self.session.add(job)
        self.session.commit()
        worker.run_voice(self.session, job)
        return self.profile()

    def test_basic_registration_is_ready_without_training(self):
        self.add_sample(0, 8.0)
        profile = self.register(tune=False)
        self.assertEqual(profile.status, "ready")
        self.assertEqual(profile.reference_index, 0)
        self.assertIsNone(profile.s3gen_status)
        self.assertEqual(self.queued("voice_train"), [])
        self.assertEqual([n.kind for n in self.notices()], ["voice_ready"])
        self.assertNotIn("다듬는", self.notices()[0].text)

    def test_registration_with_tuning_queues_training(self):
        for index in range(9):
            self.add_sample(index, 15.0)
        profile = self.register(tune=True)
        self.assertEqual(profile.status, "ready")
        self.assertEqual(profile.s3gen_status, "queued")
        train = self.queued("voice_train")
        self.assertEqual([j.payload for j in train], [{"voice_id": profile.tts_voice_id}])
        self.assertIn("다듬는 동안에도", self.notices()[0].text)

    def test_training_keeps_registered_sentence_after_more_recordings(self):
        self.add_sample(0, 8.0, snr=20)
        profile = self.register(tune=False)
        self.assertEqual(profile.reference_index, 0)
        # 나중에 녹음한 차분한 문장이 더 좋은 후보여도, 등록한 문장(0번)으로 학습한다
        self.add_sample(1, 9.0, snr=40)
        samples = self.session.scalars(select(VoiceSample).where(VoiceSample.user_id == self.uid)).all()
        self.assertEqual(worker._pick_reference(samples, LEGACY_SENTENCES).index, 1)
        self.assertEqual(worker._registered_reference(samples, profile).index, 0)

        calls = []

        def runner(clips, ref_id, reference, voice_id, work, still_current):
            calls.append(ref_id)
            return s3gen.Outcome(False, "no_gain", {"score": {}})

        with patch.object(worker.s3gen_remote, "run", side_effect=runner):
            self.run_training(profile)
        self.assertEqual(calls, ["s00"])

    def run_training(self, profile):
        profile.s3gen_status = "queued"
        job = Job(type="voice_train", user_id=self.uid, payload={"voice_id": profile.tts_voice_id})
        self.session.add(job)
        self.session.commit()
        worker.run_voice_train(self.session, job)
        return job

    def test_training_results_are_announced_and_kept_voice_can_be_retrained(self):
        self.add_sample(0, 8.0)
        profile = self.register(tune=False)
        adapter = TEST_ROOT / "adapter.safetensors"
        adapter.write_bytes(b"adapter")
        cases = [
            (s3gen.Outcome(False, "no_gain", {"score": {}}), "skipped", "voice_tune_skipped", worker.TUNE_SKIPPED_TEXT),
            (s3gen.Outcome(False, "not_enough_audio", {}), "skipped", "voice_tune_skipped", worker.TUNE_NOISY_TEXT),
            (s3gen.Outcome(True, "improved", {"score": {}}, adapter=adapter), "applied", "voice_tuned", worker.TUNE_APPLIED_TEXT),
        ]
        for outcome, status, kind, text in cases:
            with patch.object(worker.s3gen_remote, "run", return_value=outcome):
                self.run_training(self.profile())
            profile = self.profile()
            self.assertEqual(profile.s3gen_status, status)
            self.assertEqual(profile.s3gen_report["result"], outcome.reason)
            self.assertEqual((self.notices()[-1].kind, self.notices()[-1].text), (kind, text))
        self.assertTrue(storage.abs_path(profile.s3gen_adapter_path).exists())

    def test_final_training_failure_is_announced(self):
        self.add_sample(0, 8.0)
        profile = self.register(tune=False)
        job = self.run_training_job_only(profile)
        job.last_error = "TrainingError: boom"
        worker._on_final_failure(self.session, job)
        profile = self.profile()
        self.assertEqual(profile.s3gen_status, "failed")
        self.assertEqual((self.notices()[-1].kind, self.notices()[-1].text), ("voice_tune_failed", worker.TUNE_FAILED_TEXT))

    def run_training_job_only(self, profile):
        profile.s3gen_status = "training"
        job = Job(type="voice_train", user_id=self.uid, payload={"voice_id": profile.tts_voice_id})
        self.session.add(job)
        self.session.commit()
        return job


if __name__ == "__main__":
    unittest.main()
