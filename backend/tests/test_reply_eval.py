"""답장 분석 채점 도구(evals/reply_eval.py) 시험: 가짜 CLOVA·가짜 분석 서버로 세 단계 채점과 저장 결과 재사용을 본다.

    python -m unittest discover -s backend/tests -v
"""

import csv
import io
import json
import shutil
import unittest
import uuid
import wave
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import httpx
import numpy as np

from _test_support import TEST_ROOT, settings
from app.services import reply_analysis, reply_gpu, reply_llm
from evals import reply_eval

TEXT_SET = Path(reply_eval.__file__).with_name("reply_eval_text.csv")
CALM = {"mood": "평온", "health": "없음", "mind": "없음", "life": "없음", "level": "없음", "change": "이전 기록 없음",
        "evidence": [], "summary": "평소처럼 지내신대요.", "confidence": "확실"}
USUAL = {"ok": True, "pitch_st": 12.0, "pitch_range_st": 8.0, "loudness_db": -27.0, "rate": 4.2, "pause_ratio": 0.2}
DOWN = dict(USUAL, loudness_db=-38.0, rate=3.4)


def wav_bytes(seconds=1.0, rate=16000):
    pcm = (0.3 * np.sin(2 * np.pi * 200 * np.arange(int(seconds * rate)) / rate) * 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


class Fake:
    def __init__(self):
        self.clova, self.stt, self.prosody, self.calls = [], [], [], []
        self.fail = False

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.calls.append(path)
        if self.fail:
            return httpx.Response(500, json={"status": {"code": "50000"}})
        if path == "/health":
            return httpx.Response(200, json={"ok": True})
        if path == "/stt":
            text, problems = self.stt.pop(0)
            return httpx.Response(200, json={"text": text, "problems": problems, "duration": 1.0, "seconds": 0.1})
        if path == "/prosody":
            return httpx.Response(200, json=self.prosody.pop(0))
        content = json.dumps(self.clova.pop(0) if self.clova else CALM, ensure_ascii=False)
        return httpx.Response(200, json={"status": {"code": "20000"}, "result": {
            "message": {"role": "assistant", "content": content}, "usage": {"promptTokens": 1500, "completionTokens": 100}}})


class ReplyEvalTests(unittest.TestCase):
    def setUp(self):
        self.fake = Fake()
        mock = httpx.MockTransport(self.fake.handle)
        for target, attr, value in ((reply_gpu, "transport", mock), (reply_llm, "transport", mock),
                                    (reply_llm, "_sleep", lambda _s: None),
                                    (settings, "reply_llm_api_key", "test-clova-key"),
                                    (settings, "reply_analysis_url", "http://gpu.test")):
            p = patch.object(target, attr, value)
            p.start()
            self.addCleanup(p.stop)
        self.dir = TEST_ROOT / f"eval-{uuid.uuid4().hex[:8]}"
        self.dir.mkdir()
        self.addCleanup(shutil.rmtree, self.dir, True)

    def run_eval(self, *args):
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(reply_eval.main(list(args)), 0)
        return out.getvalue()

    def results(self, out_dir):
        with open(out_dir / "results.csv", encoding="utf-8-sig") as f:
            return {r["id"]: r for r in csv.DictReader(f)}

    def test_text_set_labels_use_schema_options(self):
        rows = reply_eval.read_set(TEXT_SET)
        self.assertEqual(len(rows), 80)
        self.assertEqual({lv: sum(r["level"] == lv for r in rows) for lv in reply_analysis.LEVELS},
                         {"없음": 40, "살펴보기": 30, "바로 연락 필요": 10})

    def test_three_stages_and_cache(self):
        self.fake.clova = [
            CALM,  # T01 정답 없음 → 맞음
            dict(CALM, health="아픔", evidence=["무릎이 아파서 계단 오르기가 힘들어", "지어낸 근거"]),  # T41: ① 없음 → ② 살펴보기
            dict(CALM, mood="가라앉음(쓸쓸·우울)", mind="죽음·살기 싫다는 말", level="살펴보기",
                 evidence=["그냥 살기가 싫다"]),  # T71: 바로 연락을 낮게 봄
        ]
        out = self.dir / "text"
        printed = self.run_eval("--set", str(TEXT_SET), "--out", str(out), "--ids", "T01,T41,T71")
        r = self.results(out)
        self.assertEqual([r["T01"]["s1"], r["T01"]["s2"]], ["없음", "없음"])
        self.assertEqual([r["T41"]["s1"], r["T41"]["s2"]], ["없음", "살펴보기"])
        self.assertEqual(r["T41"]["evidence_dropped"], "1")
        self.assertEqual(r["T71"]["s2"], "살펴보기")
        report = (out / "report.md").read_text(encoding="utf-8")
        self.assertIn("초안 정답 기준", report)
        self.assertIn("| 놓친 비율 (정답 살펴보기 이상 → '없음') | 50% (1/2", report)   # ①: T41만 놓침
        self.assertIn("'바로 연락 필요'를 낮게 본 비율 | 100% (1/1", report)
        self.assertNotIn("무릎", printed.split("# 답장 분석 채점")[0])   # 진행 표시에는 답장 글을 찍지 않는다
        self.assertEqual(self.fake.calls.count("/v3/chat-completions/HCX-007"), 3)

        self.fake.fail = True   # 저장한 결과로 다시 채점: CLOVA를 부르지 않는다
        self.run_eval("--set", str(TEXT_SET), "--out", str(out), "--ids", "T01,T41,T71", "--score-only")
        self.assertEqual(self.results(out)["T41"]["s2"], "살펴보기")
        self.assertEqual(len(self.fake.calls), 3)

    def test_voice_mismatch_only_in_stage_three(self):
        (self.dir / "wavs").mkdir()
        rows = []
        for n in range(1, 7):
            (self.dir / "wavs" / f"S1_{n:02d}.wav").write_bytes(wav_bytes(1.0 + n / 10))  # 파일마다 달라야 저장 키가 다르다
            intent = "처짐" if n == 5 else "평소"
            rows.append({"id": f"S1_{n:02d}", "speaker": "S1", "order": n, "case": "시험", "letter": "잘 지내?",
                         "audio": f"wavs/S1_{n:02d}.wav", "reply_script": "응 잘 지내", "voice_intent": intent,
                         "mood": "평온", "health": "없음", "mind": "없음", "life": "없음",
                         "level": "살펴보기" if n == 5 else "없음", "confidence": "확실", "note": "",
                         "check_1": "가", "check_2": "나"})
        with open(self.dir / "voice.csv", "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        # 받아쓰기가 같으면 CLOVA 입력도 같아서 저장한 결과를 다시 쓴다 → 답장마다 다르게
        self.fake.stt = [(f"응 잘 지내 오늘은 {day} 밥도 잘 먹어", []) for day in ("월요일", "화요일", "수요일", "목요일", "금요일")]
        self.fake.stt.append(("", ["말소리를 찾지 못함"]))
        self.fake.prosody = [USUAL] * 4 + [DOWN]
        out = self.dir / "out"
        self.run_eval("--set", str(self.dir / "voice.csv"), "--out", str(out))
        r = self.results(out)
        self.assertEqual(r["S1_03"]["voice_status"], "기록 중")
        self.assertEqual(r["S1_04"]["voice_status"], "비교")
        self.assertEqual([r["S1_05"][s] for s in ("s1", "s2", "s3")], ["없음", "없음", "살펴보기"])
        self.assertEqual(r["S1_05"]["mismatch"], "True")
        self.assertEqual(r["S1_06"]["status"], "stt_uncertain")
        self.assertEqual(self.fake.calls.count("/v3/chat-completions/HCX-007"), 5)   # 받아쓰기 불확실은 보내지 않는다
        report = (out / "report.md").read_text(encoding="utf-8")
        self.assertIn("처진 목소리로 녹음한 답장을 '목소리 처짐'으로 잡은 비율: 100% (1/1", report)


if __name__ == "__main__":
    unittest.main()
