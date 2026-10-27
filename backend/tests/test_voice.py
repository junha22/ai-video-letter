"""Recording completion uses accepted audio and the 135-second target."""

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

    def test_recording_and_dashboard_report_135_second_target(self):
        self.assertEqual(self.client.get("/api/voice").json()["target_seconds"], 135)
        self.assertEqual(self.client.get("/api/me").json()["voice"]["target_seconds"], 135)

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

    def test_less_than_135_accepted_seconds_cannot_finalize(self):
        self.add_sample(0, 134.9)
        self.add_sample(1, 20, accepted=False)
        response = self.client.post("/api/voice/finalize")
        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(self.client.get("/api/voice").json()["status"], "recording")
        with db.SessionLocal() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(Job)), 0)

    def test_135_seconds_can_finalize_once_without_extra_recording(self):
        for index in range(9):
            self.add_sample(index, 15)
        for _ in range(2):
            response = self.client.post("/api/voice/finalize")
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["status"], "processing")
            self.assertEqual(response.json()["total_seconds"], 135)
        with db.SessionLocal() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(Job).where(Job.type == "voice")), 1)
