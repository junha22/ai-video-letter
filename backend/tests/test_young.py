"""어린 시절 모드: 목소리 변환과 ComfyUI 호출 (가짜 ComfyUI로 확인한다)."""

import json
import logging
import unittest
from datetime import timedelta
from unittest.mock import MagicMock, patch

import httpx
import numpy as np
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select

from _test_support import TEST_ROOT, app, db, settings, using_isolated_database
from app import serialize, worker
from app.db import utcnow
from app.models import Message, ParentProfile, Photo, VoiceProfile
from app.services import audio, jobs, storage, young
from app.services import face as face_service
from app.worker import _young_photo

logging.getLogger("httpx").setLevel(logging.WARNING)

SR = audio.SAMPLE_RATE


def peak_hz(path) -> float:
    samples = audio.read_wav(path)
    spectrum = np.abs(np.fft.rfft(samples * np.hanning(len(samples))))
    return float(np.fft.rfftfreq(len(samples), 1 / SR)[spectrum.argmax()])


class MakeYoungerTest(unittest.TestCase):
    def test_raises_pitch_and_keeps_length(self):
        path = TEST_ROOT / "young_voice.wav"
        t = np.arange(2 * SR) / SR
        audio.write_wav(path, 0.3 * np.sin(2 * np.pi * 200 * t))
        before = audio.wav_duration(path)

        audio.make_younger(path, 1.25)

        # 립싱크가 어긋나지 않도록 길이는 그대로 (atempo 경계에서 몇 ms 차이)
        self.assertAlmostEqual(audio.wav_duration(path), before, delta=0.03)
        self.assertAlmostEqual(peak_hz(path), 250, delta=5)


class FakeComfy:
    """ComfyUI의 /upload/image → /prompt → /history → /view → /free 흐름을 흉내 낸다"""

    def __init__(self, prompt_status: int = 200):
        self.prompt_status = prompt_status
        self.paths: list[str] = []
        self.workflow: dict | None = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.paths.append(request.url.path)
        if request.url.path == "/upload/image":
            return httpx.Response(200, json={"name": "ongi_user_1.jpg", "subfolder": "", "type": "input"})
        if request.url.path == "/prompt":
            if self.prompt_status != 200:
                return httpx.Response(self.prompt_status, json={"error": "missing model"})
            self.workflow = json.loads(request.content)["prompt"]
            return httpx.Response(200, json={"prompt_id": "p1"})
        if request.url.path == "/history/p1":
            image = {"filename": "young_temp_00001_.png", "subfolder": "", "type": "temp"}
            return httpx.Response(200, json={"p1": {"status": {"status_str": "success"},
                                                    "outputs": {young.OUTPUT_NODE: {"images": [image]}}}})
        if request.url.path == "/view":
            return httpx.Response(200, content=b"PNG-BYTES")
        return httpx.Response(200, json={})


def fake_client(handler):
    return lambda: httpx.Client(base_url="http://comfy.test", transport=httpx.MockTransport(handler))


class GenerateTest(unittest.TestCase):
    def test_sends_workflow_and_returns_image(self):
        comfy = FakeComfy()
        with patch.object(young, "_client", fake_client(comfy)):
            data = young.generate(b"JPEG", "ongi_user_1.jpg", age=6)

        self.assertEqual(data, b"PNG-BYTES")
        self.assertEqual(comfy.workflow["5"]["inputs"]["image"], "ongi_user_1.jpg")
        self.assertIn("6-year-old child", comfy.workflow["6"]["inputs"]["prompt"])
        self.assertEqual(comfy.workflow["9"]["inputs"]["noise_seed"], young.SEED)
        # 다 만든 뒤 GPU를 TTS·영상 서버에 돌려준다
        self.assertEqual(comfy.paths[-1], "/free")

    def test_remake_uses_given_seed(self):
        comfy = FakeComfy()
        with patch.object(young, "_client", fake_client(comfy)):
            young.generate(b"JPEG", "ongi_user_1.jpg", age=6, seed=1234)
        self.assertEqual(comfy.workflow["9"]["inputs"]["noise_seed"], 1234)

    def test_rejected_workflow_is_not_retried(self):
        comfy = FakeComfy(prompt_status=400)
        with patch.object(young, "_client", fake_client(comfy)), self.assertRaises(young.YoungPhotoError) as ctx:
            young.generate(b"JPEG", "ongi_user_1.jpg", age=6)
        self.assertFalse(ctx.exception.retryable)
        self.assertEqual(comfy.paths[-1], "/free")


class YoungPhotoTest(unittest.TestCase):
    def test_without_comfyui_uses_original_photo(self):
        photo = Photo(user_id=1, path="users/1/photo/photo.jpg", width=800, height=1000, face=[1, 2, 3, 4])
        with patch.object(settings, "comfyui_url", ""):
            path, face = _young_photo(None, photo)
        self.assertEqual(path, settings.data_dir / "users/1/photo/photo.jpg")
        self.assertEqual(face, [1, 2, 3, 4])

    def test_reuses_made_photo(self):
        photo = Photo(user_id=1, path="users/1/photo/photo.jpg", width=800, height=1000, face=[1, 2, 3, 4],
                      young_path="users/1/photo/young.png", young_face=[5, 6, 7, 8])
        with patch.object(settings, "comfyui_url", "http://comfy.test"), \
                patch.object(young, "generate", side_effect=AssertionError("다시 만들면 안 된다")):
            path, face = _young_photo(None, photo)
        self.assertEqual(path, settings.data_dir / "users/1/photo/young.png")
        self.assertEqual(face, [5, 6, 7, 8])

    def _make(self, alt_box):
        """기본 검출기는 못 찾는 만든 사진. 두 번째 검출기 결과(alt_box)에 따라 달라진다"""
        original = settings.data_dir / "users/2/photo/photo.jpg"
        original.parent.mkdir(parents=True, exist_ok=True)
        original.write_bytes(b"JPEG")
        photo = Photo(user_id=2, path="users/2/photo/photo.jpg", width=800, height=1000, face=[1, 2, 3, 4])
        missed = face_service.PhotoCheck(image=Image.new("RGB", (896, 1152), "white"), problems=["얼굴을 찾지 못했어요."])
        with patch.object(settings, "comfyui_url", "http://comfy.test"), \
                patch.object(young, "generate", return_value=b"PNG"), \
                patch.object(face_service, "check", return_value=missed), \
                patch.object(face_service, "find_face_alt", return_value=alt_box):
            return photo, _young_photo(MagicMock(), photo)

    def test_second_detector_finds_face(self):
        # 조금 멀리서 찍은 구도의 아이 얼굴은 기본 검출기가 놓쳐서 영상 만들기가 실패했다
        photo, (path, box) = self._make([248, 301, 350, 350])
        self.assertEqual(box, [248, 301, 350, 350])
        self.assertEqual(photo.young_face, [248, 301, 350, 350])
        self.assertTrue(path.exists())

    def test_fails_when_no_detector_finds_face(self):
        with self.assertRaises(young.YoungPhotoError) as ctx:
            self._make(None)
        self.assertFalse(ctx.exception.retryable)


FACE = [10, 20, 300, 300]


def checked(data: bytes) -> face_service.PhotoCheck:
    """얼굴 검사 대신: b"no-face"만 얼굴이 없는 사진으로 본다"""
    image = Image.new("RGB", (64, 80), "white")
    if data == b"no-face":
        return face_service.PhotoCheck(image=image, problems=["얼굴을 찾지 못했어요."])
    return face_service.PhotoCheck(image=image, face=FACE)


class YoungPreviewTest(unittest.TestCase):
    """영상 전에 어린 시절 사진 만들어 보기 → (다시 만들기) → 그 사진으로 영상 만들기"""

    def setUp(self):
        self.assertTrue(using_isolated_database())
        storage.delete_tree(TEST_ROOT / "users")
        db.Base.metadata.drop_all(db.engine)
        db.init_db()
        for name, value in (("dev_login", True), ("comfyui_url", "http://comfy.test")):
            p = patch.object(settings, name, value)
            p.start()
            self.addCleanup(p.stop)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.assertEqual(self.client.post("/api/auth/dev-login", json={"name": "young preview test"}).status_code, 200)
        self.uid = self.client.get("/api/me").json()["user"]["id"]
        self.assertEqual(self.client.post("/api/consent", json={"voice": True, "face": True, "parent_receive": True}).status_code, 200)
        rid = self.client.post("/api/recipients", json={"nickname": "엄마", "relation": "어머니"}).json()["id"]
        self.assertEqual(self.client.get("/api/voice").status_code, 200)
        original = storage.user_dir(self.uid, "photo") / "photo.jpg"
        original.write_bytes(b"JPEG")
        with db.SessionLocal() as session:
            profile = session.scalar(select(VoiceProfile).where(VoiceProfile.user_id == self.uid))
            profile.status = "ready"
            parent = session.scalar(select(ParentProfile).where(ParentProfile.user_id == self.uid))
            session.add(Photo(user_id=self.uid, path=storage.rel_path(original), width=800, height=1000, face=[1, 2, 3, 4]))
            message = Message(user_id=self.uid, parent_id=parent.id, recipient_id=rid, memo="저녁 먹었어?",
                              template="greeting", script="엄마, 저녁은 드셨어요? 오늘도 따뜻하게 챙겨 드세요.")
            session.add(message)
            session.commit()
            self.message_id = message.id

    def state(self):
        response = self.client.get("/api/photo/young")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def make(self, data: bytes):
        """만들기(다시 만들기)를 누르고 워커가 그 작업을 처리한다"""
        self.assertTrue(self.client.post("/api/photo/young").json()["making"])
        with db.SessionLocal() as session:
            job = jobs.claim(session)
            self.assertEqual(job.type, "young_photo")
            with patch.object(young, "generate", return_value=data) as generate, \
                    patch.object(face_service, "check", side_effect=checked), \
                    patch.object(face_service, "find_face_alt", return_value=None):
                worker.process(session, job)
        self.seed = generate.call_args.args[3]
        return self.state()

    def render(self):
        return self.client.post(f"/api/messages/{self.message_id}/render", json={"emotion": "neutral", "young": True})

    def photo_row(self):
        with db.SessionLocal() as session:
            return session.scalar(select(Photo).where(Photo.user_id == self.uid))

    def test_make_then_render(self):
        self.assertEqual(self.state(), {"available": True, "making": False, "error": None, "url": None})
        # 만들어 보기 전에는 어린 시절 모드로 영상을 만들 수 없다
        self.assertEqual(self.render().status_code, 409)

        state = self.make(b"a")
        self.assertFalse(state["making"])
        image = self.client.get(state["url"])
        self.assertEqual((image.status_code, image.headers["content-type"]), (200, "image/png"))
        self.assertEqual(self.photo_row().young_face, FACE)

        response = self.render()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["young"])

    def test_remake_uses_new_seed_and_replaces_photo(self):
        first = self.make(b"a")
        first_seed = self.seed
        second = self.make(b"b")
        self.assertNotEqual(self.seed, first_seed)
        self.assertNotEqual(first["url"], second["url"])  # 브라우저가 예전 사진을 보여 주지 않게 주소가 바뀐다

    def test_failed_remake_keeps_previous_photo(self):
        first = self.make(b"a")
        state = self.make(b"no-face")
        self.assertEqual(state["error"], serialize.YOUNG_NO_FACE)
        self.assertEqual(state["url"], first["url"])
        self.assertEqual(self.render().status_code, 200)

    def test_new_upload_clears_photo(self):
        self.make(b"a")
        ok = face_service.PhotoCheck(image=Image.new("RGB", (800, 1000), "white"), face=[1, 2, 3, 4])
        with patch.object(face_service, "check", return_value=ok):
            self.assertTrue(self.client.post("/api/photo", files={"file": ("me.jpg", b"JPEG", "image/jpeg")}).json()["ok"])
        self.assertIsNone(self.state()["url"])
        self.assertFalse((storage.user_dir(self.uid, "photo") / "young.png").exists())

    def test_photo_replaced_while_making_is_dropped(self):
        self.assertTrue(self.client.post("/api/photo/young").json()["making"])
        with db.SessionLocal() as session:
            photo = session.scalar(select(Photo).where(Photo.user_id == self.uid))
            photo.created_at = utcnow() + timedelta(seconds=1)  # 만드는 사이에 사진을 새로 올림
            session.commit()
            job = jobs.claim(session)
            with patch.object(young, "generate", side_effect=AssertionError("바뀐 사진으로 만들면 안 된다")):
                worker.process(session, job)
        self.assertEqual(self.state(), {"available": True, "making": False, "error": None, "url": None})

    def test_without_comfyui_only_voice_changes(self):
        with patch.object(settings, "comfyui_url", ""):
            self.assertFalse(self.state()["available"])
            self.assertEqual(self.client.post("/api/photo/young").status_code, 409)
            # 사진을 못 바꾸는 서버는 만들어 보지 않아도 영상을 만든다 (원본 사진 + 어린 목소리)
            self.assertEqual(self.render().status_code, 200)


if __name__ == "__main__":
    unittest.main()
