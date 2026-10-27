"""Recording completion uses accepted audio and the 90-second target."""

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from _test_support import TEST_ROOT, app, db, settings
from app.models import Job, VoiceSample


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

    def test_recording_and_dashboard_report_ninety_second_target(self):
        self.assertEqual(self.client.get("/api/voice").json()["target_seconds"], 90)
        self.assertEqual(self.client.get("/api/me").json()["voice"]["target_seconds"], 90)

    def test_less_than_ninety_accepted_seconds_cannot_finalize(self):
        self.add_sample(0, 89.9)
        self.add_sample(1, 20, accepted=False)
        response = self.client.post("/api/voice/finalize")
        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(self.client.get("/api/voice").json()["status"], "recording")
        with db.SessionLocal() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(Job)), 0)

    def test_ninety_seconds_can_finalize_once_without_extra_recording(self):
        for index in range(9):
            self.add_sample(index, 10)
        for _ in range(2):
            response = self.client.post("/api/voice/finalize")
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["status"], "processing")
            self.assertEqual(response.json()["total_seconds"], 90)
        with db.SessionLocal() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(Job).where(Job.type == "voice")), 1)
