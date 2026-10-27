"""TTS reference audio is cut at a pause inside 10 seconds instead of mid-word."""

import unittest

import numpy as np

import _test_support  # noqa: F401  격리 설정 (DATA_DIR 등)을 먼저 적용한다
from app.models import VoiceSample
from app.services import audio
from app.worker import _pick_reference

SR = audio.SAMPLE_RATE
RNG = np.random.default_rng(0)


def speech(seconds: float) -> np.ndarray:
    # 말소리 대신 크기가 출렁이는 소리 (약 -20dBFS, 쉼으로 볼 만큼 작아지지 않는다)
    t = np.arange(int(seconds * SR)) / SR
    return (0.14 * np.sin(2 * np.pi * 180 * t) * (0.7 + 0.3 * np.sin(2 * np.pi * 3 * t))).astype(np.float32)


def silence(seconds: float) -> np.ndarray:
    return RNG.normal(0, 10 ** (-45 / 20), int(seconds * SR)).astype(np.float32)  # 배경 잡음 -45dBFS


def soft(seconds: float) -> np.ndarray:
    # 구절 사이 숨처럼 얕은 쉼: 일정하게 -34dBFS (말소리보다 약 14dB 작음)
    t = np.arange(int(seconds * SR)) / SR
    return (0.14 * 10 ** (-14 / 20) * np.sin(2 * np.pi * 180 * t)).astype(np.float32)


def clip(*parts: tuple[str, float]) -> np.ndarray:
    make = {"speech": speech, "pause": silence, "soft": soft}
    return np.concatenate([make[kind](s) for kind, s in parts])


class TrimReferenceTests(unittest.TestCase):
    def test_long_script_is_cut_in_the_last_sentence_gap_inside_ten_seconds(self):
        samples = clip(("pause", 0.15), ("speech", 3.0), ("pause", 0.4), ("speech", 3.5), ("pause", 0.4),
                       ("speech", 4.0), ("pause", 0.15))
        out = audio.trim_reference(samples)
        cut = len(out) / SR
        # 두 번째 쉼(7.05~7.45초) 안에서 자르고, 마지막은 쉼이라 말이 끊기지 않는다
        self.assertGreaterEqual(cut, 7.05)
        self.assertLessEqual(cut, 7.45)
        tail = out[-int(0.05 * SR):]
        self.assertLess(20 * np.log10(np.sqrt(np.mean(tail**2))), -35)

    def test_clear_pause_wins_over_a_later_shallow_one(self):
        samples = clip(("pause", 0.15), ("speech", 4.5), ("pause", 0.4), ("speech", 3.0), ("soft", 0.3),
                       ("speech", 4.0), ("pause", 0.15))
        cut = len(audio.trim_reference(samples)) / SR
        self.assertGreaterEqual(cut, 4.65)  # 조용한 쉼(4.65~5.05초)
        self.assertLessEqual(cut, 5.05)

    def test_shallow_pause_is_used_when_there_is_no_clear_one(self):
        samples = clip(("pause", 0.15), ("speech", 4.5), ("soft", 0.3), ("speech", 3.0), ("soft", 0.3),
                       ("speech", 4.0), ("pause", 0.15))
        cut = len(audio.trim_reference(samples)) / SR
        self.assertGreaterEqual(cut, 7.95)  # 더 늦은 얕은 쉼(7.95~8.25초)
        self.assertLessEqual(cut, 8.25)

    def test_short_break_inside_a_word_is_not_a_pause(self):
        # 받침·파열음처럼 0.05초 끊기는 곳은 앞뒤 말소리에 묻혀서 자르지 않는다
        samples = clip(("pause", 0.15), ("speech", 6.0), ("pause", 0.05), ("speech", 6.0), ("pause", 0.15))
        cut = len(audio.trim_reference(samples)) / SR
        self.assertGreaterEqual(cut, 9.45)
        self.assertLessEqual(cut, 0.15 + 9.5)

    def test_reference_within_limit_is_unchanged(self):
        samples = clip(("pause", 0.15), ("speech", 4.0), ("pause", 0.4), ("speech", 4.0), ("pause", 0.15))
        self.assertEqual(len(audio.trim_reference(samples)), len(samples))

    def test_without_any_pause_it_is_cut_at_the_limit(self):
        samples = clip(("pause", 0.15), ("speech", 12.0), ("pause", 0.15))
        cut = len(audio.trim_reference(samples)) / SR
        # 서버처럼 가장 큰 소리 기준 35dB 안쪽을 소리로 보므로 배경 잡음(-45dBFS)부터 9.5초를 센다
        self.assertGreaterEqual(cut, 9.45)
        self.assertLessEqual(cut, 0.15 + 9.5)

    def test_pause_too_early_is_not_used(self):
        # 4초 전의 쉼에서 자르면 참조가 너무 짧아지므로 쓰지 않는다
        samples = clip(("pause", 0.15), ("speech", 2.0), ("pause", 0.5), ("speech", 10.0), ("pause", 0.15))
        cut = len(audio.trim_reference(samples)) / SR
        # 서버처럼 가장 큰 소리 기준 35dB 안쪽을 소리로 보므로 배경 잡음(-45dBFS)부터 9.5초를 센다
        self.assertGreaterEqual(cut, 9.45)
        self.assertLessEqual(cut, 0.15 + 9.5)


class PickReferenceTests(unittest.TestCase):
    SENTENCES = [{"kind": "calm"}, {"kind": "statement"}, {"kind": "question"}, {"kind": "calm"}]

    def sample(self, index, duration, snr=30.0):
        return VoiceSample(index=index, duration=duration, snr_db=snr, ok=True)

    def test_long_calm_script_is_preferred_since_it_is_trimmed(self):
        picked = _pick_reference([self.sample(0, 14.0), self.sample(1, 7.0), self.sample(2, 6.5)], self.SENTENCES)
        self.assertEqual(picked.index, 0)

    def test_too_short_recording_still_loses(self):
        picked = _pick_reference([self.sample(3, 4.0), self.sample(1, 7.0)], self.SENTENCES)
        self.assertEqual(picked.index, 1)


if __name__ == "__main__":
    unittest.main()
