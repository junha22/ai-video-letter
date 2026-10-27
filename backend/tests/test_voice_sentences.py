"""Recording scripts cover three categories without hiding variety after the time target."""

from collections import Counter
import unittest

import _test_support  # noqa: F401
from app.services import sentences


class VoiceScriptPoolTests(unittest.TestCase):
    def test_pool_has_requested_category_sizes_and_reading_guidance(self):
        self.assertEqual(Counter(s["category"] for s in sentences.SENTENCES), {
            "emotion": 12, "calm": 8, "pronunciation": 10,
        })
        self.assertEqual(len({s["text"] for s in sentences.SENTENCES}), 30)
        for sentence in sentences.SENTENCES:
            with self.subTest(text=sentence["text"]):
                self.assertTrue(sentence["hint"])
                self.assertTrue(sentence["guide"])
                self.assertGreaterEqual(len(sentence["text"]), 60)
                self.assertLessEqual(len(sentence["text"]), 110)
                if sentence["category"] == "calm":
                    self.assertEqual(sentence["kind"], "calm")
                if sentence["category"] == "pronunciation":
                    self.assertTrue(sentence["focus"])
        emotion_hints = {s["hint"] for s in sentences.SENTENCES if s["category"] == "emotion"}
        self.assertGreaterEqual(len(emotion_hints), 8)

    def test_assignment_keeps_full_pool_and_variety_from_the_first_three_takes(self):
        expected_texts = {s["text"] for s in sentences.SENTENCES}
        for _ in range(20):
            assigned = sentences.assign()
            self.assertEqual(len(assigned), 30)
            self.assertEqual({s["text"] for s in assigned}, expected_texts)
            self.assertEqual(assigned[0]["kind"], "calm")
            # The first 24 scripts can form eight balanced groups before calm runs out.
            for offset in range(0, 24, 3):
                self.assertEqual({s["category"] for s in assigned[offset:offset + 3]}, {
                    "calm", "emotion", "pronunciation",
                })

    def test_legacy_guidance_does_not_rewrite_a_saved_script(self):
        saved = {"kind": "question", "text": "아빠, 오늘 산책은 다녀오셨어요?"}
        original = dict(saved)
        guide = sentences.guidance(saved)
        self.assertEqual(saved, original)
        self.assertEqual(guide["category"], "emotion")
        self.assertTrue(guide["hint"])
        self.assertTrue(guide["guide"])
        self.assertEqual(guide["focus"], [])


if __name__ == "__main__":
    unittest.main()
