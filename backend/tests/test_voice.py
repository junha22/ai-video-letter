"""Voice registration is two-step: one full sentence registers the basic voice, 135 seconds unlocks optional tuning."""

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from _test_support import TEST_ROOT, app, db, settings
from app.models import Job, VoiceProfile, VoiceSample


class VoiceRecordingTargetTests(unittest.TestCase):
    def setUp(self):
        self.assertEqual(settings.data_dir, TEST_ROOT)
        db.Base.metadata.drop_all(db.engine)
        db.init_db()
        enabled = patch.object(settings, "dev_login", True)
        enabled.start()
        self.addCleanup(enabled.stop)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.assertEqual(self.client.post("/api/auth/dev-login", json={"name": "voice recording test"}).status_code, 200)
        self.uid = self.client.get("/api/me").json()["user"]["id"]
        self.assertEqual(self.client.post("/api/consent", json={
            "voice": True, "face": True, "parent_receive": True,
        }).status_code, 200)
        self.assertEqual(self.client.get("/api/voice").status_code, 200)

    def add_sample(self, index, duration, accepted=True):
        with db.SessionLocal() as session:
            session.add(VoiceSample(user_id=self.uid, index=index, text="test sentence",
                                    path=f"test-only-{index}.wav", duration=duration,
                                    speech_db=-20, snr_db=30, ok=accepted))
            session.commit()

    def tuning_enabled(self):
        """wemeet TTS + 음색 학습을 GPU PC에 맡기는 설정 (학습 환경 파일 검사 없이 학습을 고를 수 있다)"""
        for name, value in (("tts_provider", "wemeet"), ("s3gen_training", True), ("s3gen_remote_url", "http://gpu.test/train")):
            p = patch.object(settings, name, value)
            p.start()
            self.addCleanup(p.stop)

    def make_ready(self, tuning=None):
        with db.SessionLocal() as session:
            profile = session.scalar(select(VoiceProfile).where(VoiceProfile.user_id == self.uid))
            profile.status = "ready"
            profile.tts_voice_id = "user_test_voice"
            profile.reference_index = 0
            profile.s3gen_status = tuning
            session.commit()

    def jobs_of(self, type):
        with db.SessionLocal() as session:
            return session.scalars(select(Job).where(Job.type == type, Job.status == "queued")).all()

    def test_recording_and_dashboard_report_basic_and_tuning_targets(self):
        for state in (self.client.get("/api/voice").json(), self.client.get("/api/me").json()["voice"]):
            self.assertEqual(state["target_seconds"], 135)
            self.assertEqual(state["basic_seconds"], 6.0)
            self.assertFalse(state["basic_ready"])
            self.assertFalse(state["tuning_available"])  # 테스트 설정은 TTS_PROVIDER=local
            self.assertFalse(state["can_tune"])
        self.add_sample(0, 8.0)
        self.assertTrue(self.client.get("/api/me").json()["voice"]["basic_ready"])

    def test_voice_state_includes_category_specific_guidance(self):
        scripts = self.client.get("/api/voice").json()["sentences"]
        self.assertEqual(len(scripts), 30)
        self.assertEqual(scripts[0]["category"], "calm")
        self.assertEqual({s["category"] for s in scripts[:3]}, {"calm", "emotion", "pronunciation"})
        for script in scripts:
            self.assertTrue(script["hint"])
            self.assertTrue(script["guide"])
            self.assertIsInstance(script["focus"], list)
            if script["category"] == "pronunciation":
                self.assertTrue(script["focus"])

    def test_legacy_profile_keeps_saved_order_and_recording_until_reset(self):
        old_scripts = [
            {"kind": "calm", "text": "오늘은 집 근처를 천천히 걸었어요."},
            {"kind": "question", "text": "엄마, 오늘 하루는 어떠셨어요?"},
            {"kind": "statement", "text": "보내 주신 반찬을 맛있게 먹었어요."},
            {"kind": "exclamation", "text": "아빠, 생신 정말 축하드려요!"},
        ]
        with db.SessionLocal() as session:
            profile = session.scalar(select(VoiceProfile).where(VoiceProfile.user_id == self.uid))
            profile.sentences = old_scripts
            session.commit()
        self.add_sample(0, 9.2)
        state = self.client.get("/api/voice").json()
        self.assertEqual([s["text"] for s in state["sentences"]], [s["text"] for s in old_scripts])
        self.assertEqual([s["index"] for s in state["sentences"]], list(range(4)))
        self.assertEqual(state["sentences"][0]["sample"], {"duration": 9.2, "ok": True})
        self.assertEqual(state["total_seconds"], 9.2)
        for script in state["sentences"]:
            self.assertIn(script["category"], {"calm", "emotion"})
            self.assertTrue(script["guide"])
        response = self.client.post("/api/voice/reset")
        self.assertEqual(response.status_code, 200, response.text)
        reset_state = response.json()
        self.assertEqual(len(reset_state["sentences"]), 30)
        self.assertEqual(reset_state["total_seconds"], 0)
        self.assertTrue(all(s["sample"] is None for s in reset_state["sentences"]))
        self.assertEqual({s["category"] for s in reset_state["sentences"][:3]}, {
            "calm", "emotion", "pronunciation",
        })

    def test_needs_one_full_sentence_to_finalize(self):
        # 짧게 끊어 읽은 녹음만 있거나, 통과하지 못한 녹음은 기본 등록 조건이 아니다
        self.add_sample(0, 5.9)
        self.add_sample(1, 5.9)
        self.add_sample(2, 20, accepted=False)
        response = self.client.post("/api/voice/finalize")
        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(self.client.get("/api/voice").json()["status"], "recording")
        with db.SessionLocal() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(Job)), 0)

    def test_one_full_sentence_registers_basic_voice_once_without_tuning(self):
        self.add_sample(0, 8.0)
        for _ in range(2):
            response = self.client.post("/api/voice/finalize")
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["status"], "processing")
            self.assertEqual(response.json()["total_seconds"], 8.0)
        voice_jobs = self.jobs_of("voice")
        self.assertEqual(len(voice_jobs), 1)
        self.assertEqual(voice_jobs[0].payload, {"tune": False})

    def test_finalize_with_tuning_needs_target_seconds_and_tuning_available(self):
        for index in range(9):
            self.add_sample(index, 15)
        # 이 서버에서 학습할 수 없으면 고를 수 없다
        response = self.client.post("/api/voice/finalize", json={"tune": True})
        self.assertEqual(response.status_code, 400, response.text)
        self.tuning_enabled()
        with db.SessionLocal() as session:
            session.execute(VoiceSample.__table__.delete().where(VoiceSample.index == 8))
            session.commit()
        response = self.client.post("/api/voice/finalize", json={"tune": True})
        self.assertEqual(response.status_code, 400, response.text)
        self.assertIn("15초 더", response.json()["detail"])
        self.add_sample(8, 15)
        response = self.client.post("/api/voice/finalize", json={"tune": True})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.jobs_of("voice")[0].payload, {"tune": True})

    def test_ready_voice_can_record_more_and_start_optional_tuning(self):
        self.tuning_enabled()
        self.add_sample(0, 8.0)
        self.make_ready()
        state = self.client.get("/api/voice").json()
        self.assertTrue(state["tuning_available"])
        self.assertFalse(state["can_tune"])
        # 등록에 쓴 문장은 다시 녹음하지 않는다 (파일을 읽기 전에 막는다)
        response = self.client.post("/api/voice/samples/0", files={"file": ("take", b"not audio")})
        self.assertEqual(response.status_code, 409, response.text)
        response = self.client.post("/api/voice/tune")
        self.assertEqual(response.status_code, 400, response.text)
        self.assertIn("127초 더", response.json()["detail"])

        for index in range(1, 9):
            self.add_sample(index, 16)
        self.assertTrue(self.client.get("/api/voice").json()["can_tune"])
        for _ in range(2):  # 두 번 눌러도 학습은 하나만 들어간다
            response = self.client.post("/api/voice/tune")
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["tuning"], "queued")
            self.assertFalse(response.json()["can_tune"])
        train = self.jobs_of("voice_train")
        self.assertEqual(len(train), 1)
        self.assertEqual(train[0].payload, {"voice_id": "user_test_voice"})
        # 학습하는 동안에는 더 녹음할 수 없다
        response = self.client.post("/api/voice/samples/9", files={"file": ("take", b"not audio")})
        self.assertEqual(response.status_code, 409, response.text)

    def test_tuning_can_be_retried_after_basic_voice_was_kept_but_not_after_applied(self):
        self.tuning_enabled()
        for index in range(9):
            self.add_sample(index, 15)
        for tuning in ("skipped", "failed"):
            self.make_ready(tuning)
            state = self.client.get("/api/voice").json()
            self.assertTrue(state["can_tune"], tuning)
            response = self.client.post("/api/voice/tune")
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["tuning"], "queued")
        self.make_ready("applied")
        self.assertFalse(self.client.get("/api/voice").json()["can_tune"])
        self.assertEqual(self.client.post("/api/voice/tune").status_code, 409)
        self.assertEqual(self.client.post("/api/voice/samples/9", files={"file": ("take", b"x")}).status_code, 409)

    def test_tune_needs_registered_voice(self):
        self.tuning_enabled()
        for index in range(9):
            self.add_sample(index, 15)
        self.assertEqual(self.client.post("/api/voice/tune").status_code, 409)
        self.assertEqual(self.jobs_of("voice_train"), [])
