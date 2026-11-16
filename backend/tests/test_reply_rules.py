"""부모님 답장 분석 규칙 단위 시험 (GPU·음성 파일·외부 서비스 없이).

정답지 reply_analysis_reference.py 맨 아래 자체 시험을 바탕으로 만들었다. 규칙 값을 바꾸면 여기서 깨진다.
    python -m unittest discover -s backend/tests -v
"""

import unittest
from unittest.mock import patch

import numpy as np

import _test_support  # noqa: F401  backend 폴더를 import 경로에 넣는다
from app.services import reply_analysis as ra
from gpu_worker import reply_audio

REPLY = "요즘 무릎이 아파서 잘 못 걸어. 그래도 밥은 잘 먹어."
OUT = {"mood": "평온", "health": "아픔", "mind": "없음", "life": "없음", "level": "없음", "change": "이전 기록 없음",
       "evidence": ["요즘 무릎이 아파서 잘 못 걸어", "지어낸 문장"], "summary": "무릎이 아프시대요.", "confidence": "확실"}
CALM = dict(OUT, health="없음", evidence=[])
USUAL = [{"ok": True, "pitch_st": 12.0, "pitch_range_st": 8.0, "loudness_db": -27.0, "rate": 4.2, "pause_ratio": 0.2}] * 3
DOWN = {"ok": True, "pitch_st": 12.1, "pitch_range_st": 7.9, "loudness_db": -38.0, "rate": 3.4, "pause_ratio": 0.21}


def hist(n, **values):
    base = {"date": "2026-11-01", "mood": "평온", "level": "없음", "health": "없음", "mind": "없음", "life": "없음",
            "summary": "평소처럼 지내세요.", "reply_chars": 30}
    return [dict(base, **values) for _ in range(n)]


class PromptTests(unittest.TestCase):
    def test_prompt_id_matches_reference(self):
        self.assertEqual(ra.PROMPT_ID, "v2-6af325")

    def test_build_prompt_turns_thinking_off(self):
        p = ra.build_prompt(ra.SYSTEM, "질문", False)
        self.assertTrue(p.startswith("<|im_start|>tool_list\n<|im_end|>\n<|im_start|>system\n"))
        self.assertTrue(p.endswith("<|im_start|>assistant/think\n<|im_end|>\n<|im_start|>assistant\n"))

    def test_user_prompt_layout(self):
        user = ra.user_prompt("요즘 어떠세요?", [], "잘 지내")
        self.assertEqual(user, "[자녀 편지]\n요즘 어떠세요?\n\n[최근 답장 기록 (오래된 것부터)]\n없음 (첫 답장)\n\n[이번 답장 받아쓰기]\n잘 지내")

    def test_history_text_lists_signals(self):
        text = ra.history_text(hist(1, health="아픔", level="살펴보기", summary="무릎이 아프시대요."))
        self.assertEqual(text, "- 2026-11-01 | 기분 평온 | 수준 살펴보기 | 신호 건강 아픔 | 무릎이 아프시대요.")
        self.assertIn("신호 없음", ra.history_text(hist(1)))

    def test_mask_pii(self):
        self.assertEqual(ra.mask_pii("010-1234-5678로 전화해"), "[전화번호]로 전화해")
        self.assertEqual(ra.mask_pii("계좌 123-45-678901 알려 줘"), "계좌 [번호] 알려 줘")
        self.assertEqual(ra.mask_pii("3시에 병원 가"), "3시에 병원 가")

    def test_llm_params_match_reference(self):
        self.assertEqual({k: ra.LLM_PARAMS[k] for k in ("temperature", "top_p", "repeat_penalty", "seed")},
                         {"temperature": 0.2, "top_p": 0.6, "repeat_penalty": 1.05, "seed": 1})
        self.assertEqual(ra.LLM_PARAMS["stop"], ["<|im_end|>", "<|endofturn|>", "<|stop|>"])

    def test_clova_params_match_kaggle_settings(self):
        # 서비스는 CLOVA Studio HCX-007. 값은 Kaggle 설정과 같고, 형식 강제 때문에 추론은 끈다
        self.assertEqual(ra.CLOVA_PARAMS, {"thinking": {"effort": "none"}, "maxCompletionTokens": 1024, "temperature": 0.2,
                                           "topP": 0.6, "topK": 0, "repetitionPenalty": 1.05, "seed": 1})
        # 형식 강제가 지원하는 키워드만 쓴다 (pattern 등은 지원하지 않는다)
        allowed = {"type", "enum", "items", "maxItems", "properties", "required"}

        def keywords(schema):
            for key, value in schema.items():
                yield key
                if key == "properties":
                    for sub in value.values():
                        yield from keywords(sub)
                elif isinstance(value, dict):
                    yield from keywords(value)
        self.assertLessEqual(set(keywords(ra.SCHEMA)), allowed)

    def test_check_output(self):
        ra.check_output(dict(OUT))
        for broken in (dict(OUT, mood="행복"), dict(OUT, evidence="문장"), dict(OUT, evidence=["a"] * 6),
                       {k: v for k, v in OUT.items() if k != "summary"}, ["not", "dict"]):
            with self.assertRaises(ValueError):
                ra.check_output(broken)


class PostprocessTests(unittest.TestCase):
    def test_drops_evidence_not_in_reply_and_raises_level_for_signal(self):
        r = ra.postprocess(dict(OUT), REPLY, [])
        self.assertEqual(r["level"], "살펴보기")
        self.assertEqual(r["evidence_dropped"], 1)
        self.assertEqual(r["evidence"], ["요즘 무릎이 아파서 잘 못 걸어"])
        self.assertIn("신호가 있는데", r["level_reasons"][0])

    def test_evidence_comparison_ignores_spacing_and_punctuation(self):
        r = ra.postprocess(dict(OUT, evidence=["요즘무릎이 아파서, 잘 못 걸어!"]), REPLY, [])
        self.assertEqual(r["evidence_dropped"], 0)

    def test_voice_mismatch_raises_level(self):
        r = ra.postprocess(dict(CALM), REPLY, [], voice_mismatch=True)
        self.assertEqual(r["level"], "살펴보기")
        self.assertTrue(r["voice_mismatch"])
        self.assertIn("말·목소리 불일치", r["level_reasons"][0])
        self.assertEqual(ra.postprocess(dict(CALM), REPLY, [])["level"], "없음")

    def test_urgent_without_signal_marks_unsure(self):
        r = ra.postprocess(dict(CALM, level="바로 연락 필요"), REPLY, [])
        self.assertEqual((r["level"], r["confidence"]), ("바로 연락 필요", "애매"))

    def test_low_mood_three_times_raises_level(self):
        low = dict(CALM, mood="가라앉음(쓸쓸·우울)")
        r = ra.postprocess(low, REPLY, hist(2, mood="가라앉음(쓸쓸·우울)"))
        self.assertEqual(r["level"], "살펴보기")
        self.assertIn("가라앉은 기분이 3번 연속", r["trend_alerts"])

    def test_trend_alerts(self):
        r = ra.postprocess(dict(OUT, change="나빠짐"), REPLY, hist(2, level="살펴보기", health="아픔", reply_chars=100))
        self.assertEqual(r["trend_alerts"], ["살펴보기 이상이 3번 연속", "같은 건강 신호가 다시 나옴: 아픔",
                                             "답장이 평소보다 많이 짧음", "LLM 판단: 지난 기록보다 나빠짐"])
        # 지난 답장이 1개뿐이면 흐름 경고를 붙이지 않는다
        self.assertEqual(ra.postprocess(dict(OUT), REPLY, hist(1, level="살펴보기", reply_chars=100))["trend_alerts"],
                         [])

    def test_warnings(self):
        r = ra.postprocess(dict(OUT, evidence=["없는 말"], summary="ok"), REPLY, [])
        self.assertEqual(len(r["warnings"]), 2)


class ProsodyCompareTests(unittest.TestCase):
    def test_voice_down_sentence(self):
        c = ra.compare_prosody(DOWN, USUAL)
        self.assertTrue(c["voice_down"])
        self.assertEqual(c["text"], "평소보다 목소리가 작아요 · 말이 느려요")
        self.assertEqual(c["down"], ["목소리가 작아요", "말이 느려요"])

    def test_recording_until_three_past_replies(self):
        c = ra.compare_prosody(DOWN, USUAL[:2])
        self.assertEqual(c["status"], "기록 중")
        self.assertEqual(c["text"], "평소 목소리를 기록하는 중이에요 (2/3)")
        self.assertFalse(c["voice_down"])
        # 재지 못한 지난 답장은 세지 않는다
        self.assertEqual(ra.compare_prosody(DOWN, USUAL[:2] + [{"ok": False}])["status"], "기록 중")

    def test_one_changed_item_is_not_voice_down(self):
        c = ra.compare_prosody(dict(USUAL[0], loudness_db=-38.0), USUAL)
        self.assertFalse(c["voice_down"])
        self.assertEqual(c["text"], "평소와 비슷해요 (조금 다른 점: 목소리가 작아요)")
        self.assertEqual(ra.compare_prosody(USUAL[0], USUAL)["text"], "평소와 비슷해요")

    def test_unmeasured_reply(self):
        c = ra.compare_prosody({"ok": False, "reason": "말소리가 3초보다 짧아 운율을 재지 않음"}, USUAL)
        self.assertEqual((c["status"], c["voice_down"]), ("측정 못 함", False))

    def test_uses_only_last_ten_past_replies(self):
        loud = [dict(USUAL[0], loudness_db=-10.0)] * 5
        c = ra.compare_prosody(USUAL[0], loud + USUAL * 4)  # 마지막 10개는 모두 평소 값
        self.assertEqual(c["n_past"], 10)
        self.assertEqual(c["text"], "평소와 비슷해요")

    def test_mismatch_moods(self):
        self.assertEqual(ra.MISMATCH_MOODS, ("밝음", "평온", "판단 어려움"))


class DisplayTests(unittest.TestCase):
    def done(self, **result):
        out = ra.postprocess(dict(OUT, **result), REPLY, [])
        return ra.display("done", "voice", out, ra.compare_prosody(DOWN, USUAL))

    def test_done_card(self):
        d = self.done()
        self.assertEqual((d["level_label"], d["mood_text"]), ("살펴보기", "평온해 보여요"))
        self.assertEqual(d["signals"], [{"area": "건강", "value": "아픔"}])
        self.assertEqual(d["voice_text"], "평소보다 목소리가 작아요 · 말이 느려요")
        self.assertIsNone(d["unsure_text"])
        self.assertEqual(d["notice"], "AI가 정리한 내용이에요. 진단이 아니니 음성을 함께 들어 보세요.")
        self.assertNotIn("items", str(d))  # 목소리 측정 숫자는 보내지 않는다

    def test_mismatch_and_unsure_text(self):
        out = ra.postprocess(dict(CALM, confidence="애매"), REPLY, [], voice_mismatch=True)
        d = ra.display("done", "voice", out, ra.compare_prosody(DOWN, USUAL))
        self.assertEqual(d["mismatch_text"], "말은 괜찮다고 하시지만 목소리가 평소보다 처져 있어요. 한번 연락해 보세요.")
        self.assertEqual(d["unsure_text"], "AI 판단이 확실하지 않아요")

    def test_status_messages(self):
        self.assertEqual(ra.display("queued", "text", None, None)["message"], "AI가 답장을 정리하고 있어요.")
        self.assertEqual(ra.display("stt_uncertain", "voice", None, None)["message"],
                         "말소리가 잘 들리지 않아 내용을 정리하지 못했어요. 직접 들어 보세요.")
        failed = ra.display("failed", "text", None, None)
        self.assertEqual((failed["status"], failed["notice"]),
                         ("failed", "AI가 정리한 내용이에요. 진단이 아니니 답장을 함께 읽어 보세요."))

    def test_level_and_mood_wording(self):
        self.assertEqual([ra.LEVEL_UI[k][0] for k in ra.LEVELS], ["평소와 같아요", "살펴보기", "바로 연락해 보세요"])
        self.assertEqual([ra.MOOD_UI[k] for k in ra.MOODS], ["밝아 보여요", "평온해 보여요", "기운이 없어 보여요",
                                                            "걱정이 있어 보여요", "서운해 보여요", "기분은 판단하기 어려워요"])


class SttRuleTests(unittest.TestCase):
    def test_check_text(self):
        self.assertEqual(reply_audio.check_text("음", 3), "빈 출력")
        self.assertEqual(reply_audio.check_text("그래 그래 그래 그래 그래 그래", 5), "같은 말 반복")
        self.assertEqual(reply_audio.check_text("시청해 주셔서 감사합니다", 5), "지어내기 의심 문구")
        self.assertEqual(reply_audio.check_text("가나다라마바사아자차카타파하" * 3, 2), "길이에 비해 글자가 너무 많음(지어내기 의심)")
        self.assertIsNone(reply_audio.check_text("요즘 무릎이 아파서 잘 못 걸어", 4))

    def test_split_on_silence(self):
        sr = reply_audio.SR
        self.assertEqual(reply_audio.split_on_silence(np.ones(20 * sr, np.float32)), [(0, 20 * sr)])
        wav = np.full(60 * sr, 0.3, np.float32)
        wav[18 * sr:int(18.5 * sr)] = 0.0   # 12~25초 사이의 조용한 곳
        wav[40 * sr:int(40.5 * sr)] = 0.0
        pieces = reply_audio.split_on_silence(wav)
        self.assertEqual(pieces[0][0], 0)
        self.assertEqual(pieces[-1][1], len(wav))
        self.assertTrue(all(12 * sr <= e - s <= 25 * sr for s, e in pieces[:-1]), pieces)
        self.assertTrue(18 * sr <= pieces[0][1] <= int(18.5 * sr))

    def test_run_stt_retries_with_beam_search_and_skips_silence(self):
        sr = reply_audio.SR
        wav = np.zeros(10 * sr, np.float32)
        wav[: 5 * sr] = 0.5
        calls = []

        def transcribe(x, beams=1):
            calls.append(beams)
            return "시청해 주셔서 감사합니다" if beams == 1 else "잘 지내고 있어"

        with patch.object(reply_audio, "load_audio", return_value=wav):
            out = reply_audio.run_stt("reply.wav", transcribe)
        self.assertEqual((out["text"], out["problems"], calls), ("잘 지내고 있어", [], [1, 5]))
        with patch.object(reply_audio, "load_audio", return_value=np.zeros(5 * sr, np.float32)):
            silent = reply_audio.run_stt("reply.wav", transcribe)
        self.assertEqual(silent["problems"], ["말소리를 찾지 못함"])


class NameHidingTests(unittest.TestCase):
    """CLOVA Studio 약관상 개인정보를 넣지 않는다: DB에 있는 이름과 이메일을 가리고 호칭은 그대로 둔다"""

    def test_names_to_hide_skips_honorifics(self):
        from app.services import reply_llm
        self.assertEqual(reply_llm.names_to_hide("김민지", "민수", "엄마"), ["김민지", "민수", "민지"])
        self.assertEqual(reply_llm.names_to_hide("우리 딸", "막내", "어머님", "할머니", "", None, "형"), [])

    def test_hide_names(self):
        from app.services import reply_llm
        names = reply_llm.names_to_hide("김민지", "민수", "엄마")
        self.assertEqual(reply_llm.hide_names("민수야, 엄마는 김민지 선생님 만났어. mom.kim@example.co.kr 로 보내", names),
                         "[이름]야, 엄마는 [이름] 선생님 만났어. [이메일] 로 보내")

    def test_analysis_server_starts_without_llm_files(self):
        # LLM은 CLOVA라 GGUF·llama-server 없이도 분석 서버(받아쓰기·운율)가 정상이어야 한다
        import os
        import sys
        from fastapi.testclient import TestClient
        sys.path.insert(0, str(_test_support.TESTS_DIR.parent / "gpu_worker"))
        with patch.dict(os.environ):  # 서버가 읽는 실제 backend/.env가 시험 환경에 남지 않게
            import reply_analysis_server as server
        with TestClient(server.app) as client:
            health = client.get("/health")
            self.assertEqual((health.status_code, health.json()["ok"]), (200, True))
            self.assertEqual(client.post("/llm", json={}).status_code, 404)


if __name__ == "__main__":
    unittest.main()
