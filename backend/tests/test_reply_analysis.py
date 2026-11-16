"""부모님 답장 분석 통합 시험: 가짜 분석 서버·가짜 CLOVA(httpx.MockTransport)로 업로드 → 워커 → 자녀·공개 화면 응답까지.

GPU·외부 서비스 없이 임시 DB·임시 미디어·고정 시계를 쓴다 (test_conversations.py와 같은 방식).
    python -m unittest discover -s backend/tests -v
"""

import io
import json
import logging
import shutil
import unittest
import wave
from contextlib import ExitStack, contextmanager
from datetime import datetime, timedelta
from unittest.mock import patch

import httpx
import numpy as np

from _test_support import TEST_ROOT as _TEST_ROOT, app, db, settings, using_isolated_database
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from app.models import (
    Job, Message, Notification, ParentProfile, Recipient, ReplyAnalysis, ReplyAnalysisConsent, SeniorReply, ShareLink,
)
from app.services import jobs, replies, reply_analysis, reply_gpu, reply_llm, storage

NOW = datetime(2026, 11, 12, 3, 0, 0)
logging.getLogger("httpx").setLevel(logging.WARNING)

CALM = {"mood": "평온", "health": "없음", "mind": "없음", "life": "없음", "level": "없음", "change": "비슷함",
        "evidence": [], "summary": "평소처럼 잘 지내신대요.", "confidence": "확실"}
PAIN = {"mood": "걱정·불안", "health": "넘어짐·다침", "mind": "없음", "life": "혼자 해결 못 하는 일", "level": "바로 연락 필요",
        "change": "나빠짐", "evidence": ["어제 넘어져서 일어나질 못했어", "지어낸 근거"], "summary": "넘어지셔서 도움이 필요하대요.",
        "confidence": "확실"}
USUAL = {"ok": True, "pitch_st": 12.0, "pitch_range_st": 8.0, "loudness_db": -27.0, "rate": 4.2, "pause_ratio": 0.2,
         "pitch_hz": 199.9, "duration": 3.0, "speech_sec": 2.5, "seconds": 0.4}
DOWN = dict(USUAL, loudness_db=-38.0, rate=3.4)
TRANSCRIPT = "요즘 잘 지내. 밥도 잘 먹고. 급하면 010-1234-5678로 전화해"
CLOVA_PATH = "/v3/chat-completions/HCX-007"
PRIVATE_KEYS = {"analysis", "level", "level_label", "summary", "mood", "mood_text", "voice_text", "stt_text", "prosody",
                "result", "signals", "trend_alerts"}


def wav_bytes(seconds=3.0, rate=16000, freq=200):
    t = np.arange(int(seconds * rate)) / rate
    pcm = (0.3 * np.sin(2 * np.pi * freq * t) * 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


def keys_deep(value):
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from keys_deep(item)
    elif isinstance(value, list):
        for item in value:
            yield from keys_deep(item)


class FakeAnalysisServer:
    """GPU PC 분석 서버(받아쓰기·운율)와 CLOVA Studio 흉내. 응답을 차례로 꺼내 쓰고, 받은 요청을 남긴다.
    clova 목록: dict = 그 판단 JSON, str = 그대로 content(깨진 JSON 시험), (상태 코드, 본문) = 오류 응답"""

    def __init__(self):
        self.stt, self.prosody, self.clova, self.calls, self.llm_requests = [], [], [], [], []
        self.gpu_status = 200    # GPU PC 분석 서버가 꺼졌을 때
        self.clova_status = 200  # CLOVA가 계속 실패할 때
        self.on_call = None

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.calls.append(path)
        if self.on_call:
            self.on_call(path)
        if path == CLOVA_PATH:
            return self.handle_clova(request)
        if self.gpu_status != 200:
            return httpx.Response(self.gpu_status, json={"detail": "가짜 서버 오류"})
        if path == "/health":
            return httpx.Response(200, json={"ok": True})
        if path == "/stt":
            text, problems = self.stt.pop(0) if self.stt else (TRANSCRIPT, [])
            return httpx.Response(200, json={"text": text, "duration": 3.0, "pieces": 1, "problems": problems,
                                             "seconds": 1.0, "load_seconds": 5.0, "model": "BuzzASR/korean"})
        if path == "/prosody":
            return httpx.Response(200, json=self.prosody.pop(0) if self.prosody else USUAL)
        return httpx.Response(404)

    def handle_clova(self, request: httpx.Request) -> httpx.Response:
        self.llm_requests.append({"body": json.loads(request.content), "headers": request.headers})
        if self.clova_status != 200:
            return httpx.Response(self.clova_status, json={"status": {"code": "50000", "message": "가짜 오류"}})
        item = self.clova.pop(0) if self.clova else CALM
        if isinstance(item, tuple):
            return httpx.Response(item[0], json=item[1])
        content = item if isinstance(item, str) else json.dumps(item, ensure_ascii=False)
        return httpx.Response(200, json={
            "status": {"code": "20000", "message": "OK"},
            "result": {"message": {"role": "assistant", "content": content},
                       "usage": {"promptTokens": 1500, "completionTokens": 120, "totalTokens": 1620}},
        })


class ReplyAnalysisTests(unittest.TestCase):
    def setUp(self):
        for target, value in (("dev_login", True), ("reply_analysis_enabled", True)):
            p = patch.object(settings, target, value)
            p.start()
            self.addCleanup(p.stop)
        self.assertEqual(settings.data_dir, _TEST_ROOT)
        self.assertTrue(using_isolated_database(), str(db.engine.url))
        db.Base.metadata.drop_all(db.engine)
        db.init_db()
        # 사용자 ID가 시험마다 1부터 다시 시작하므로, 앞 시험이 남긴 임시 미디어를 지운다 (철회 때 지운 파일 수를 세려고)
        shutil.rmtree(_TEST_ROOT / "users", ignore_errors=True)
        self.fake = FakeAnalysisServer()
        mock = httpx.MockTransport(self.fake.handle)
        for target, attr, value in ((reply_gpu, "transport", mock), (reply_llm, "transport", mock),
                                    (reply_llm, "_sleep", lambda _seconds: None),
                                    (settings, "reply_llm_api_key", "test-clova-key")):
            p = patch.object(target, attr, value)
            p.start()
            self.addCleanup(p.stop)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.clock_stack = ExitStack()
        self.addCleanup(self.clock_stack.close)
        for target in ("app.services.conversations.utcnow", "app.routers.watch.utcnow", "app.routers.messages.utcnow",
                       "app.services.replies.utcnow"):
            self.clock_stack.enter_context(patch(target, return_value=NOW))

    # ---------------------------------------------------------------- 준비 ----
    def assert_ok(self, response, status=200):
        self.assertEqual(response.status_code, status, response.text)
        return response.json()

    def owner(self, name="owner", token="room-token"):
        self.assert_ok(self.client.post("/api/auth/dev-login", json={"name": name}))
        uid = self.assert_ok(self.client.get("/api/me"))["user"]["id"]
        self.assert_ok(self.client.post("/api/consent", json={"voice": True, "face": True, "parent_receive": True}))
        self.assert_ok(self.client.put("/api/parent", json={
            "nickname": "엄마", "relation": "어머니", "phone": "01012345678", "child_call_name": "민수",
        }))
        rid = self.assert_ok(self.client.get("/api/recipients"))[0]["id"]
        with db.SessionLocal() as session:
            parent = session.scalar(select(ParentProfile).where(ParentProfile.user_id == uid))
            message = Message(user_id=uid, parent_id=parent.id, recipient_id=rid, memo="메모", template="greeting",
                              script="엄마, 요즘 어떻게 지내세요?", status="approved", created_at=NOW - timedelta(hours=1),
                              approved_at=NOW - timedelta(hours=1), duration=3.0, captions=[])
            session.add(message)
            session.flush()
            session.add(ShareLink(message_id=message.id, token=token, expires_at=NOW + timedelta(days=1000)))
            session.commit()
            self.message_id = message.id
        return uid, rid

    def enable(self, rid, token="room-token", senior=True):
        state = self.assert_ok(self.client.put(f"/api/recipients/{rid}/reply-analysis", json={"enabled": True, "agree": True}))
        self.assertTrue(state["enabled"])
        if senior:
            self.assert_ok(self.client.post(f"/api/watch/{token}/voice-notice"))

    def voice(self, client_id, data=None, token="room-token", message_id=None):
        form = {"client_id": client_id}
        if message_id:
            form["message_id"] = str(message_id)
        return self.client.post(f"/api/watch/{token}/voice-replies", data=form,
                                files={"file": ("reply.webm", data or wav_bytes(), "audio/webm")})

    def text(self, client_id, value="잘 지내고 있어", token="room-token"):
        return self.client.post(f"/api/watch/{token}/replies", json={"text": value, "client_id": client_id})

    def run_jobs(self):
        from app import worker
        with db.SessionLocal() as session:
            while job := jobs.claim(session):
                worker.process(session, job)

    def feed_replies(self, rid):
        events = self.assert_ok(self.client.get(f"/api/conversations/{rid}/feed"))["events"]
        return [event for event in events if event["type"] == "reply"]

    def analysis_rows(self):
        with db.SessionLocal() as session:
            return session.scalars(select(ReplyAnalysis).order_by(ReplyAnalysis.id)).all()

    # ---------------------------------------------------------------- 시험 ----
    def test_feature_off_keeps_existing_behavior(self):
        with patch.object(settings, "reply_analysis_enabled", False):
            uid, rid = self.owner()
            reply = self.assert_ok(self.text("off-reply-1"))
            self.assertEqual(set(reply), {"type", "id", "created_at", "date", "text", "message_id"})
            public = self.assert_ok(self.client.get("/api/watch/room-token/conversation"))
            self.assertNotIn("voice_reply", public)
            self.assertNotIn("voice_reply", self.assert_ok(self.client.get("/api/watch/room-token/feed")))
            self.assertEqual(set(self.feed_replies(rid)[0]), {"type", "id", "created_at", "date", "text", "message_id"})
            self.assertNotIn("reply_analysis", self.assert_ok(self.client.get(f"/api/recipients/{rid}")))
            self.assertNotIn("reply_analysis", self.assert_ok(self.client.get("/api/health")))
            self.assertEqual(self.client.get(f"/api/recipients/{rid}/reply-analysis").status_code, 404)
            self.assertEqual(self.client.put(f"/api/recipients/{rid}/reply-analysis",
                                             json={"enabled": True, "agree": True}).status_code, 404)
            self.assertEqual(self.voice("off-voice-1").status_code, 404)
            self.assertEqual(self.client.post("/api/watch/room-token/voice-notice").status_code, 404)
            with db.SessionLocal() as session:
                self.assertEqual(session.scalar(select(func.count()).select_from(Job).where(Job.type == "reply_analysis")), 0)
                note = session.scalar(select(Notification).where(Notification.kind == "senior_reply"))
                self.assertEqual(note.text, "엄마님이 답글을 남기셨어요: 잘 지내고 있어")
            self.assertEqual(self.analysis_rows(), [])
            deleted = self.assert_ok(self.client.post("/api/consent/withdraw"))["deleted"]
            self.assertFalse({"reply_audio_files", "reply_analyses", "analysis_notifications"} & set(deleted))
        self.assertEqual(self.fake.calls, [])

    def test_voice_replies_build_usual_voice_and_flag_mismatch(self):
        uid, rid = self.owner()
        public = self.assert_ok(self.client.get("/api/watch/room-token/conversation"))
        self.assertEqual(public["voice_reply"]["available"], False)  # 자녀가 켜기 전에는 녹음 버튼이 없다
        self.assert_ok(self.client.put(f"/api/recipients/{rid}/reply-analysis", json={"enabled": True, "agree": True}))
        public = self.assert_ok(self.client.get("/api/watch/room-token/conversation"))
        self.assertEqual((public["voice_reply"]["available"], public["voice_reply"]["notice_needed"]), (True, True))
        self.assertIn("민수님께만 보여 드려요", public["voice_reply"]["notice"])
        self.assert_ok(self.client.post("/api/watch/room-token/voice-notice"))
        self.assertFalse(self.assert_ok(self.client.get("/api/watch/room-token/conversation"))["voice_reply"]["notice_needed"])

        self.fake.prosody = [USUAL, USUAL, USUAL, DOWN, USUAL]
        for n in range(5):
            event = self.assert_ok(self.voice(f"voice-reply-{n}", message_id=self.message_id))
            self.assertEqual((event["kind"], event["text"]), ("voice", ""))
            self.assertTrue(event["audio_url"].startswith("/api/watch/room-token/replies/"))
            self.run_jobs()
        rows = self.analysis_rows()
        self.assertEqual([row.status for row in rows], ["done"] * 5)
        self.assertEqual([row.voice["text"] for row in rows[:3]],
                         [f"평소 목소리를 기록하는 중이에요 ({n}/3)" for n in range(3)])
        self.assertTrue(rows[3].voice["voice_down"])
        self.assertEqual((rows[3].level, rows[3].voice_mismatch), ("살펴보기", True))
        self.assertEqual((rows[4].voice["text"], rows[4].level), ("평소와 비슷해요", "없음"))
        self.assertEqual(rows[0].prompt_id, "v2-6af325")

        # CLOVA에는 가린 받아쓰기·최근 기록 3개만 들어가고 목소리 정보는 들어가지 않는다
        prompts = [request["body"]["messages"][1]["content"] for request in self.fake.llm_requests]
        self.assertIn("[전화번호]", prompts[0])
        self.assertNotIn("010-1234-5678", prompts[0])
        self.assertIn("엄마, 요즘 어떻게 지내세요?", prompts[0])
        self.assertIn("없음 (첫 답장)", prompts[0])
        self.assertEqual(prompts[4].count("| 기분 평온 |"), 3)
        for prompt in prompts:
            self.assertNotIn("목소리가 작아요", prompt)
            self.assertNotIn("loudness", prompt)
        self.assertEqual(self.fake.llm_requests[0]["body"]["temperature"], 0.2)
        self.assertEqual((rows[0].llm_model, rows[0].timings["prompt_tokens"], rows[0].timings["llm_attempts"]),
                         ("HCX-007", 1500, 1))
        self.assertNotIn("ngl", rows[0].timings)

        owner_events = self.feed_replies(rid)
        self.assertEqual([event["text"] for event in owner_events], [TRANSCRIPT] * 5)  # 자녀 화면에는 자동 받아쓰기
        card = owner_events[3]["analysis"]
        self.assertEqual(card["level_label"], "살펴보기")
        self.assertEqual(card["mismatch_text"], "말은 괜찮다고 하시지만 목소리가 평소보다 처져 있어요. 한번 연락해 보세요.")
        self.assertEqual(card["voice_text"], "평소보다 목소리가 작아요 · 말이 느려요")
        self.assertEqual(card["notice"], "AI가 정리한 내용이에요. 진단이 아니니 음성을 함께 들어 보세요.")
        with db.SessionLocal() as session:
            notes = session.scalars(select(Notification).where(Notification.kind.in_(("reply_check", "reply_alert")))).all()
            self.assertEqual([(n.kind, n.text) for n in notes], [("reply_check", "엄마님 답장에 살펴볼 내용이 있어요")])

        # 공개 대화방에는 분석·받아쓰기가 어디에도 없다
        public = self.assert_ok(self.client.get("/api/watch/room-token/conversation"))
        self.assertFalse(PRIVATE_KEYS & set(keys_deep(public)), PRIVATE_KEYS & set(keys_deep(public)))
        self.assertNotIn("밥도 잘 먹고", json.dumps(public, ensure_ascii=False))
        # 시니어 링크의 채팅 피드도 같다: 녹음 버튼 정보만 있고, 분석·받아쓰기는 없다
        public_feed = self.assert_ok(self.client.get("/api/watch/room-token/feed"))
        self.assertFalse(PRIVATE_KEYS & set(keys_deep(public_feed)), PRIVATE_KEYS & set(keys_deep(public_feed)))
        self.assertNotIn("밥도 잘 먹고", json.dumps(public_feed, ensure_ascii=False))
        voice_events = [e for e in public_feed["events"] if e.get("kind") == "voice"]
        self.assertEqual(len(voice_events), 5)
        self.assertTrue(all(e["text"] == "" and e["audio_url"].startswith("/api/watch/room-token/") for e in voice_events))
        self.assertTrue(public_feed["voice_reply"]["available"])
        audio_url = public["events"][-1]["audio_url"]
        played = self.client.get(audio_url)
        self.assertEqual((played.status_code, played.headers["content-type"]), (200, "audio/wav"))
        self.assertEqual(self.client.get(owner_events[0]["audio_url"]).status_code, 200)

        # 포트폴리오에는 자동 받아쓰기를 표시하고, 다음 영상 대본 맥락에도 받아쓰기가 들어간다 (분석 결과는 없음)
        portfolio = self.assert_ok(self.client.post(f"/api/recipients/{rid}/portfolio", params={"month": "2026-11"}))
        report = portfolio["portfolio"]
        self.assertTrue(all(item.get("voice") for item in report["representative_replies"]))
        self.assertIn("음성 답장은 자동 받아쓰기로 정리해서 틀린 글자가 있을 수 있습니다.", report["caveats"])
        from app.routers.messages import _conversation_context
        with db.SessionLocal() as session:
            draft = Message(user_id=uid, recipient_id=rid, memo="", template="greeting")
            context = _conversation_context(session, draft)
        self.assertEqual(context["replies"], [TRANSCRIPT] * 3)  # 대본 맥락은 최근 답장 3개 (CONTEXT_REPLIES)

    def test_stt_uncertain_stops_before_prosody_and_llm(self):
        uid, rid = self.owner()
        self.enable(rid)
        self.fake.stt = [("시청해 주셔서 감사합니다", ["0~3초: 지어내기 의심 문구"])]
        self.assert_ok(self.voice("uncertain-voice"))
        self.run_jobs()
        row = self.analysis_rows()[0]
        self.assertEqual((row.status, row.prosody, row.result), ("stt_uncertain", None, None))
        self.assertEqual(self.fake.calls, ["/stt"])
        event = self.feed_replies(rid)[0]
        self.assertEqual(event["text"], "")  # 불확실한 받아쓰기는 답장 글로 쓰지 않는다
        self.assertEqual(event["analysis"]["message"], "말소리가 잘 들리지 않아 내용을 정리하지 못했어요. 직접 들어 보세요.")
        with db.SessionLocal() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(Notification).where(
                Notification.kind.in_(("reply_check", "reply_alert")))), 0)
        from app.routers.messages import _conversation_context
        with db.SessionLocal() as session:
            self.assertIsNone(_conversation_context(session, Message(user_id=uid, recipient_id=rid, memo="", template="greeting")))

    def test_text_reply_alert_and_consent_order(self):
        uid, rid = self.owner()
        self.enable(rid, senior=False)
        self.assert_ok(self.text("before-notice"))  # 시니어가 안내를 확인하기 전 답장은 분석하지 않는다
        self.assertEqual(self.analysis_rows(), [])
        self.assert_ok(self.client.post("/api/watch/room-token/voice-notice"))
        self.fake.clova = [PAIN]
        reply = self.assert_ok(self.text("after-notice", "어제 넘어져서 일어나질 못했어. 보일러도 고장 났어."))
        self.run_jobs()
        self.assertEqual(self.fake.calls, [CLOVA_PATH])  # 글 답장은 받아쓰기·운율 없이
        rows = self.analysis_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0].level, rows[0].result["evidence_dropped"]), ("바로 연락 필요", 1))
        events = {event["id"]: event for event in self.feed_replies(rid)}
        self.assertIsNone(events[reply["id"] - 1]["analysis"])
        card = events[reply["id"]]["analysis"]
        self.assertEqual((card["level_label"], card["voice_text"]), ("바로 연락해 보세요", None))
        self.assertEqual(card["signals"], [{"area": "건강", "value": "넘어짐·다침"}, {"area": "생활·안전", "value": "혼자 해결 못 하는 일"}])
        self.assertEqual(card["evidence"], ["어제 넘어져서 일어나질 못했어"])
        self.assertIn("LLM 판단: 지난 기록보다 나빠짐", card["trend_alerts"])
        self.assertEqual(card["notice"], "AI가 정리한 내용이에요. 진단이 아니니 답장을 함께 읽어 보세요.")
        notes = self.assert_ok(self.client.get("/api/notifications"))["items"]
        alert = [n for n in notes if n["kind"] == "reply_alert"]
        self.assertEqual([n["text"] for n in alert], ["엄마님 답장을 확인하고 바로 연락해 보세요"])
        self.assert_ok(self.client.post(f"/api/notifications/{alert[0]['id']}/read"))
        self.assertTrue([n for n in self.assert_ok(self.client.get("/api/notifications"))["items"]
                         if n["id"] == alert[0]["id"]][0]["read"])

    def test_other_users_and_rooms_are_blocked(self):
        uid, rid = self.owner()
        self.enable(rid)
        event = self.assert_ok(self.voice("owner-voice"))
        self.run_jobs()
        owner_audio = self.feed_replies(rid)[0]["audio_url"]
        self.client.cookies.clear()
        other_uid, other_rid = self.owner("other", token="other-token")
        self.assertEqual(self.client.get(owner_audio).status_code, 404)
        self.assertEqual(self.client.get(f"/api/conversations/{rid}/feed").status_code, 404)
        self.assertEqual(self.client.put(f"/api/recipients/{rid}/reply-analysis", json={"enabled": False}).status_code, 404)
        self.assertEqual(self.client.post(f"/api/recipients/{rid}/replies/{event['id']}/analysis").status_code, 404)
        self.assertEqual(self.client.get(f"/api/recipients/{other_rid}/replies/{event['id']}/audio").status_code, 404)
        self.assertEqual(self.client.get(f"/api/watch/other-token/replies/{event['id']}/audio").status_code, 404)
        self.assertEqual(self.voice("other-room-voice", token="other-token").status_code, 403)  # 다른 대화방은 켜지 않음
        with db.SessionLocal() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(ReplyAnalysis)
                                            .where(ReplyAnalysis.user_id == other_uid)), 0)

    def test_upload_limits_retries_and_rate_limit(self):
        uid, rid = self.owner()
        self.enable(rid)
        self.assertEqual(self.voice("too-big-voice", b"0" * (10 * 1024 * 1024 + 1)).status_code, 413)
        self.assertEqual(self.voice("too-long-voice", wav_bytes(185)).status_code, 413)
        self.assertEqual(self.voice("too-short-voice", wav_bytes(0.5)).status_code, 400)
        self.assertEqual(self.voice("broken-voice", b"not audio at all").status_code, 400)
        self.assertEqual(self.voice("bad id!").status_code, 422)
        data = wav_bytes(2.0)
        first = self.assert_ok(self.voice("retry-voice-1", data))
        self.assertEqual(self.assert_ok(self.voice("retry-voice-1", data))["id"], first["id"])
        self.assertEqual(self.voice("retry-voice-1", wav_bytes(2.0, freq=300)).status_code, 409)
        self.assertEqual(self.text("retry-voice-1").status_code, 409)
        with db.SessionLocal() as session:
            reply = session.get(SeniorReply, first["id"])
            self.assertEqual((reply.kind, reply.audio_seconds), ("voice", 2.0))
            self.assertTrue(storage.abs_path(reply.audio_path).exists())
            with wave.open(str(storage.abs_path(reply.audio_path))) as w:
                self.assertEqual((w.getframerate(), w.getnchannels()), (16000, 1))
            self.assertEqual(session.scalar(select(func.count()).select_from(Job).where(Job.type == "reply_analysis")), 1)
        for n in range(9):
            self.assert_ok(self.text(f"rate-text-{n}") if n % 2 else self.voice(f"rate-voice-{n}"))
        limited = self.voice("rate-voice-over")
        self.assertEqual(limited.status_code, 429)
        self.assertEqual(self.text("rate-text-over").status_code, 429)

    def test_failures_retry_and_manual_retry(self):
        uid, rid = self.owner()
        self.enable(rid)
        reply = self.assert_ok(self.text("failing-reply"))
        self.fake.clova_status = 503  # CLOVA가 계속 5xx → 잠깐 쉬었다 다시 해도 안 되면 작업 큐가 다시 시도한다
        self.run_jobs()
        self.assertEqual(self.fake.calls.count(CLOVA_PATH), 3)  # 한 번 부르고 2번 더
        with db.SessionLocal() as session:
            job = session.scalar(select(Job).where(Job.type == "reply_analysis"))
            self.assertEqual((job.status, job.attempts), ("queued", 1))
            job.max_attempts = 1
            job.run_after = NOW - timedelta(days=1)
            session.commit()
        self.run_jobs()
        card = self.feed_replies(rid)[0]["analysis"]
        self.assertEqual((card["status"], card["can_retry"]), ("failed", True))
        self.assertEqual(card["message"], "답장을 정리하지 못했어요. 답장을 직접 읽어 보세요.")
        self.fake.clova_status = 200
        self.assertEqual(self.assert_ok(self.client.post(f"/api/recipients/{rid}/replies/{reply['id']}/analysis"))["status"],
                         "queued")
        self.assertEqual(self.client.post(f"/api/recipients/{rid}/replies/{reply['id']}/analysis").status_code, 409)
        self.run_jobs()
        self.assertEqual(self.analysis_rows()[0].status, "done")
        # JSON이 틀에 맞지 않으면 seed 2로 한 번 더 하고, 그래도 안 되면 다시 해도 같아서 바로 실패로 둔다
        self.fake.clova = [dict(CALM, mood="행복"), dict(CALM, mood="행복")]
        self.assert_ok(self.text("bad-json-reply"))
        self.run_jobs()
        with db.SessionLocal() as session:
            job = session.scalars(select(Job).where(Job.type == "reply_analysis").order_by(Job.id.desc())).first()
            self.assertEqual((job.status, job.attempts), ("failed", 1))
            self.assertNotIn("행복", job.last_error)

    def test_withdrawal_deletes_voice_files_analyses_and_notifications(self):
        uid, rid = self.owner()
        self.enable(rid)
        self.fake.clova = [PAIN]
        self.assert_ok(self.voice("withdraw-voice"))
        self.run_jobs()
        files = list((settings.data_dir / "users" / str(uid) / "replies").glob("*.wav"))
        self.assertEqual(len(files), 1)
        deleted = self.assert_ok(self.client.post("/api/consent/withdraw"))["deleted"]
        self.assertEqual((deleted["reply_audio_files"], deleted["reply_analyses"], deleted["analysis_notifications"]), (1, 1, 1))
        self.assertFalse(files[0].exists())
        with db.SessionLocal() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(ReplyAnalysis)), 0)
            self.assertEqual(session.scalar(select(func.count()).select_from(SeniorReply)), 0)
            self.assertTrue(all(c.withdrawn_at for c in session.scalars(select(ReplyAnalysisConsent))))

    def test_delete_one_reply_and_turn_off_analysis(self):
        uid, rid = self.owner()
        self.enable(rid)
        self.fake.clova = [PAIN, PAIN]
        first = self.assert_ok(self.voice("delete-voice-1"))
        second = self.assert_ok(self.voice("delete-voice-2"))
        self.run_jobs()
        with db.SessionLocal() as session:
            path = storage.abs_path(session.get(SeniorReply, first["id"]).audio_path)
        self.assert_ok(self.client.delete(f"/api/recipients/{rid}/replies/{first['id']}"))
        self.assertFalse(path.exists())
        with db.SessionLocal() as session:
            self.assertEqual(session.scalars(select(Notification.reply_id).where(Notification.reply_id.is_not(None))).all(),
                             [second["id"], second["id"]])  # 남은 답장의 도착·분석 알림만
            self.assertEqual([row.reply_id for row in session.scalars(select(ReplyAnalysis))], [second["id"]])

        # 분석하는 사이 자녀가 끄면 결과를 버린다
        third = self.assert_ok(self.voice("delete-voice-3"))

        def turn_off_during_stt(path):
            if path == "/stt":
                with db.SessionLocal() as session:
                    replies.turn_off(session, session.get(Recipient, rid))
                    session.commit()

        self.fake.on_call = turn_off_during_stt
        self.run_jobs()
        self.fake.on_call = None
        with db.SessionLocal() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(ReplyAnalysis)), 0)
            self.assertEqual(session.get(SeniorReply, third["id"]).text, "")  # 받아쓰기도 저장하지 않았다
            self.assertEqual(session.scalar(select(func.count()).select_from(Notification).where(
                Notification.kind.in_(("reply_check", "reply_alert")))), 0)
            self.assertTrue(storage.abs_path(session.get(SeniorReply, second["id"]).audio_path).exists())  # 음성은 남김
        state = self.assert_ok(self.client.get(f"/api/recipients/{rid}/reply-analysis"))
        self.assertEqual((state["enabled"], state["senior_notice"]), (False, False))
        self.assertFalse(self.assert_ok(self.client.get("/api/watch/room-token/conversation"))["voice_reply"]["available"])
        self.assertEqual(self.voice("after-off").status_code, 403)
        self.assertEqual(self.client.put(f"/api/recipients/{rid}/reply-analysis", json={"enabled": True}).status_code, 400)


    def test_clova_request_format_and_name_hiding(self):
        uid, rid = self.owner(name="김민지")
        self.enable(rid)
        self.assert_ok(self.text("clova-format", "민수야 엄마는 잘 있어. 민지도 잘 지내지? 사진은 mom.kim@example.com 으로 보내"))
        self.run_jobs()
        request = self.fake.llm_requests[0]
        body, headers = request["body"], request["headers"]
        self.assertEqual(set(body), {"messages", "responseFormat", "thinking", "maxCompletionTokens", "temperature", "topP",
                                     "topK", "repetitionPenalty", "seed"})
        self.assertEqual([m["role"] for m in body["messages"]], ["system", "user"])  # system은 1개만
        self.assertEqual(body["messages"][0]["content"], reply_analysis.SYSTEM)
        self.assertEqual(body["responseFormat"], {"type": "json", "schema": reply_analysis.SCHEMA})
        self.assertEqual((body["thinking"], body["maxCompletionTokens"], body["temperature"], body["topP"], body["topK"],
                          body["repetitionPenalty"], body["seed"]), ({"effort": "none"}, 1024, 0.2, 0.6, 0, 1.05, 1))
        self.assertEqual(headers["authorization"], "Bearer test-clova-key")
        self.assertEqual(len(headers["x-ncp-clovastudio-request-id"]), 36)
        user = body["messages"][1]["content"]
        self.assertIn("[이름]야 엄마는 잘 있어. [이름]도 잘 지내지? 사진은 [이메일] 으로 보내", user)  # 호칭 '엄마'는 그대로
        sent = json.dumps(body, ensure_ascii=False)
        for private in ("민수", "민지", "김민지", "@", "user_id", "recipient_id", "reply_id"):  # ID는 위 본문 칸 목록에도 없다
            self.assertNotIn(private, sent)
        row = self.analysis_rows()[0]
        self.assertEqual((row.status, row.llm_model, row.reply_chars), ("done", "HCX-007", len(user.split("\n")[-1])))

    def test_clova_seed_retry_and_error_handling(self):
        uid, rid = self.owner()
        self.enable(rid)
        # 깨진 JSON → seed 2로 한 번 더 → 성공
        self.fake.clova = ['{"mood": "평온", "health"', CALM]
        self.assert_ok(self.text("broken-then-ok"))
        self.run_jobs()
        self.assertEqual([r["body"]["seed"] for r in self.fake.llm_requests], [1, 2])
        row = self.analysis_rows()[0]
        self.assertEqual((row.status, row.timings["llm_attempts"], row.timings["completion_tokens"]), ("done", 2, 240))
        # 429 → 잠깐 쉬었다 다시 → 성공 (seed는 그대로)
        self.fake.llm_requests.clear()
        self.fake.clova = [(429, {"status": {"code": "42901", "message": "too many"}}), CALM]
        self.assert_ok(self.text("rate-limited-then-ok"))
        self.run_jobs()
        self.assertEqual(([r["body"]["seed"] for r in self.fake.llm_requests], self.analysis_rows()[1].status), ([1, 1], "done"))
        # 401(키 틀림)·400(형식)·200이지만 status.code가 20000이 아님 → 다시 하지 않고 바로 실패
        for n, (status, code, words) in enumerate(((401, "40100", "CLOVA 키가 없거나 틀렸어요"),
                                                   (400, "40000", "CLOVA 요청 형식이 맞지 않아요"),
                                                   (200, "40400", "CLOVA 요청이 실패했어요"))):
            self.fake.llm_requests.clear()
            self.fake.clova = [(status, {"status": {"code": code, "message": "x"}})]
            self.assert_ok(self.text(f"fatal-clova-{n}"))
            self.run_jobs()
            self.assertEqual(len(self.fake.llm_requests), 1)
            row = self.analysis_rows()[-1]
            self.assertEqual(row.status, "failed")
            self.assertIn(words, row.error)
            self.assertNotIn("test-clova-key", row.error)

    def test_text_reply_without_gpu_pc_and_missing_key(self):
        uid, rid = self.owner()
        self.enable(rid)
        self.fake.gpu_status = 503  # GPU PC가 꺼져 있어도 글 답장은 분석된다
        self.assert_ok(self.text("no-gpu-text"))
        self.run_jobs()
        self.assertEqual(self.analysis_rows()[0].status, "done")
        # 키가 없으면 받아쓰기(GPU)도 하지 않고 바로 실패한다
        self.fake.gpu_status = 200
        self.fake.calls.clear()
        with patch.object(settings, "reply_llm_api_key", ""), patch.object(settings, "naver_api_key", ""):
            self.assertEqual(self.assert_ok(self.client.get("/api/health"))["reply_llm"], "no_key")
            self.fake.calls.clear()  # 상태 확인이 부른 GPU 서버 /health는 빼고 센다
            self.assert_ok(self.voice("no-key-voice"))
            self.run_jobs()
        self.assertEqual(self.fake.calls, [])
        row = self.analysis_rows()[-1]
        self.assertEqual(row.status, "failed")
        self.assertIn("CLOVA 키가 없어요", row.error)
        # REPLY_LLM_API_KEY가 비어 있으면 NAVER_API_KEY를 쓴다
        with patch.object(settings, "reply_llm_api_key", ""), patch.object(settings, "naver_api_key", "naver-key"):
            self.assertEqual(reply_llm.api_key(), "naver-key")

    def test_consent_version_change_asks_again(self):
        uid, rid = self.owner()
        self.enable(rid)
        self.assertTrue(self.assert_ok(self.client.get(f"/api/recipients/{rid}/reply-analysis"))["enabled"])
        with patch.object(settings, "reply_analysis_consent_version", "2099-new-wording"):
            # 예전 문구에 받은 동의는 남아 있어도 인정하지 않는다 → 자녀·시니어에게 다시 묻는다
            state = self.assert_ok(self.client.get(f"/api/recipients/{rid}/reply-analysis"))
            self.assertEqual((state["enabled"], state["senior_notice"]), (False, False))
            self.assertFalse(self.assert_ok(self.client.get("/api/watch/room-token/conversation"))["voice_reply"]["available"])
            self.assert_ok(self.text("old-consent-text"))
            self.assertEqual(self.analysis_rows(), [])
            self.enable(rid)
            self.assert_ok(self.text("new-consent-text"))
            self.assertEqual(len(self.analysis_rows()), 1)
            with db.SessionLocal() as session:
                versions = sorted(c.version for c in session.scalars(select(ReplyAnalysisConsent)))
            self.assertEqual(versions, ["2026-11-clova", "2026-11-clova", "2099-new-wording", "2099-new-wording"])


if __name__ == "__main__":
    unittest.main()
