"""어린 시절 모드: 목소리 변환과 ComfyUI 호출 (가짜 ComfyUI로 확인한다)."""

import json
import unittest
from unittest.mock import patch

import httpx
import numpy as np

from _test_support import TEST_ROOT, settings
from app.models import Photo
from app.services import audio, young
from app.worker import _young_photo

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
        # 다 만든 뒤 GPU를 TTS·영상 서버에 돌려준다
        self.assertEqual(comfy.paths[-1], "/free")

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


if __name__ == "__main__":
    unittest.main()
