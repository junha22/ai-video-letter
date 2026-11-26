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
from app.services import jobs, replies, reply_analysis, reply_gpu, reply_llm, reply_month, storage

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
        self.assertIn("그중 음성 답장은 5개예요.", report["summary"])
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


    def test_month_trends_and_clova_summary(self):
        uid, rid = self.owner()
        self.enable(rid)
        knee = dict(CALM, health="병원·약", level="살펴보기", summary="무릎 때문에 병원에 다녀오셨대요.")
        plan = [("month-reply-1", "경로당에서 점심 먹었어. 반찬이 맛있더라.", dict(CALM, mood="밝음", summary="경로당에서 점심을 드셨대요."), 3),
                ("month-reply-2", "무릎이 쑤셔서 병원에 다녀왔어.", dict(knee, evidence=["무릎이 쑤셔서 병원에 다녀왔어"]), 7),
                ("month-reply-3", "또 무릎 때문에 병원 갔어.", dict(knee, evidence=["또 무릎 때문에 병원 갔어"]), 10),
                ("month-prev", "시월에 쓴 답장이야.", CALM, None)]
        ids = {}
        for client_id, value, out, day in plan:
            self.fake.clova = [out]
            ids[client_id] = self.assert_ok(self.text(client_id, value))["id"]
            self.run_jobs()
        self.assert_ok(self.voice("month-voice"))
        self.run_jobs()
        with db.SessionLocal() as session:  # 날짜를 나눈다 (한국 시간 정오), 하나는 지난달로
            for client_id, _value, _out, day in plan:
                reply = session.get(SeniorReply, ids[client_id])
                reply.created_at = datetime(2026, 11, day, 3) if day else datetime(2026, 10, 20, 3)
            session.commit()

        page = self.assert_ok(self.client.get(f"/api/recipients/{rid}/portfolio", params={"month": "2026-11"}))
        trends = page["analysis_trends"]
        # 한 달 흐름은 날짜별 (캘린더): 그날 가장 높은 수준, 답장 수는 calendar
        self.assertEqual([(d["date"], d["level"], d["label"], d["analyzed"], d["voice_down"]) for d in trends["days"]],
                         [("2026-11-03", "없음", "평소와 같아요", 1, False), ("2026-11-07", "살펴보기", "살펴보기", 1, False),
                          ("2026-11-10", "살펴보기", "살펴보기", 1, False), ("2026-11-12", "없음", "평소와 같아요", 1, False)])
        self.assertEqual(page["calendar"], [{"date": d, "reply_count": 1} for d in ("2026-11-03", "2026-11-07", "2026-11-10", "2026-11-12")])
        self.assertFalse({"timeline", "signals"} & set(trends))
        self.assertIsNone(trends["topics"])
        # 원형 그래프: 정리한 답장의 수준별 수 (+ 해결 완료, 정리 전)
        self.assertEqual([(l["key"], l["label"], l["count"]) for l in trends["levels"]],
                         [("없음", "평소와 같아요", 2), ("살펴보기", "살펴보기", 2), ("바로 연락 필요", "바로 연락해 보세요", 0),
                          ("resolved", "해결 완료", 0), ("pending", "정리 전", 0)])
        # 날짜를 누르면 보이는 그날 답장: AI 한 줄 요약 (갈래는 한 달 정리 전이라 아직 없다)
        self.assertEqual([(r["date"], r["label"], r["summary"], r["topic"]) for r in trends["replies"]][:2],
                         [("2026-11-03", "평소와 같아요", "경로당에서 점심을 드셨대요.", None),
                          ("2026-11-07", "살펴보기", "무릎 때문에 병원에 다녀오셨대요.", None)])
        # 음성 답장은 아직 평소 목소리를 기록하는 중이라 목소리 줄은 없다
        self.assertEqual({r["group"] for r in trends["compare"]["rows"]}, {"답장"})
        self.assertEqual(trends["starters"], ["병원 다녀오신 뒤 어떠신지, 약은 잘 챙기시는지 여쭤보세요."])
        # 답장 수·음성 답장 수 줄은 없다 (캘린더·원형 그래프와 겹쳐서 뺐다)
        self.assertEqual({r["label"]: (r["prev"], r["now"]) for r in trends["compare"]["rows"]},
                         {"살펴보기 이상": (0, 2), "바로 연락 필요": (0, 0)})
        self.assertEqual((trends["enough"], trends["summary"], trends["can_summarize"]), (True, None, True))
        self.assertNotIn("voice", trends)  # 목소리 흐름 칸은 뺐다 (CLOVA에 보내는 사실에는 목소리 횟수가 남는다)

        # CLOVA 정리: 답장 원문은 보내지 않고 답장별 AI 요약·분류와 센 숫자만. 정리 문장과 주제 묶음을 한 번에 받는다
        self.fake.llm_requests.clear()
        # 답장 번호: 1 = 11/3 없음, 2 = 11/7 살펴보기, 3 = 11/10 살펴보기, 4 = 11/12 없음(음성)
        self.fake.clova = [{"summary": "이번 달에는 무릎 때문에 병원에 다녀오신 이야기가 두 번 이어졌어요.", "topics": [
            {"name": "일상", "status": "평소 이야기", "replies": [1, 4, 9],                  # 9는 없는 번호
             "steps": [{"reply": 1, "label": "경로당 점심"}, {"reply": 2, "label": "다른 갈래"},     # 2는 이 갈래가 아님 → 뺌
                       {"reply": 4, "label": "치매 걱정"}]},                                     # 금지어 단계 → 뺌
            {"name": "건강", "status": "해결 완료", "replies": [2, 3],                       # 2가 남았는데 해결 완료 → 나아지는 중
             "steps": [{"reply": 2, "label": "무릎 병원"}, {"reply": 3, "label": "다시 병원"}]},
            {"name": "무릎 걱정", "status": "이어지는 중", "replies": [3], "steps": []},         # 다섯 갈래가 아님 → 버림
        ], "resolved": [
            {"reply": 2, "by": 3},   # 알려 준 답장(3)이 아직 살펴보기 → 받지 않음
            {"reply": 3, "by": 4},   # 받음: 4는 뒤에 온 평소 답장. 갈래(일상)가 달라도 된다
            {"reply": 1, "by": 4},   # 1은 살펴볼 일이 아님 → 받지 않음
            {"reply": 4, "by": 2},   # 알려 준 답장이 앞 → 받지 않음
            7, {"reply": 3},         # 형식이 틀림 → 건너뜀
        ]}]
        made = self.assert_ok(self.client.post(f"/api/recipients/{rid}/portfolio/analysis-summary", params={"month": "2026-11"}))
        self.assertEqual((made["summary"]["text"], made["summary"]["stale"]), ("이번 달에는 무릎 때문에 병원에 다녀오신 이야기가 두 번 이어졌어요.", False))
        self.assertEqual(made["topics"], [  # 답장이 많은 갈래부터 (같으면 건강·…·일상 순서)
            {"name": "건강", "status": "나아지는 중", "count": 2, "dates": ["2026-11-07", "2026-11-10"],
             "steps": [{"date": "2026-11-07", "label": "무릎 병원", "level": "살펴보기", "resolved": False},
                       {"date": "2026-11-10", "label": "다시 병원", "level": "살펴보기", "resolved": True}]},
            {"name": "일상", "status": "평소 이야기", "count": 2, "dates": ["2026-11-03", "2026-11-12"],
             "steps": [{"date": "2026-11-03", "label": "경로당 점심", "level": "없음", "resolved": False}]}])
        # 해결 완료: 캘린더(11/10은 해결 완료 색), 원형 그래프(해결 완료 1), 그날 답장(해결 완료 + 갈래)
        self.assertEqual([(d["date"], d["level"], d["label"], d["resolved"]) for d in made["days"]],
                         [("2026-11-03", "없음", "평소와 같아요", False), ("2026-11-07", "살펴보기", "살펴보기", False),
                          ("2026-11-10", "없음", "해결 완료", True), ("2026-11-12", "없음", "평소와 같아요", False)])
        self.assertEqual({l["key"]: l["count"] for l in made["levels"]},
                         {"없음": 2, "살펴보기": 1, "바로 연락 필요": 0, "resolved": 1, "pending": 0})
        self.assertEqual([(r["label"], r["resolved"], r["topic"]) for r in made["replies"] if r["date"] == "2026-11-10"],
                         [("해결 완료", True, "건강")])
        self.assertNotIn("signals", made["replies"][0])   # 해결 판정용 신호는 화면에 보내지 않는다
        body = self.fake.llm_requests[0]["body"]
        self.assertEqual(body["messages"][0]["content"], reply_month.SUMMARY_SYSTEM)
        self.assertEqual((body["responseFormat"]["schema"], body["maxCompletionTokens"]), (reply_month.SUMMARY_SCHEMA, 1000))
        facts = body["messages"][1]["content"]
        self.assertIn("[부르는 말] 엄마", facts)
        self.assertIn("건강 병원·약 2번 (11월 7일, 11월 10일)", facts)
        self.assertIn("- [2] 11월 7일 | 살펴보기", facts)   # 주제 묶음이 가리키는 답장 번호
        self.assertIn("요약: 무릎 때문에 병원에 다녀오셨대요.", facts)
        for raw in ("반찬이 맛있더라", "또 무릎 때문에 병원 갔어", "밥도 잘 먹고"):
            self.assertNotIn(raw, facts)
        again = self.assert_ok(self.client.get(f"/api/recipients/{rid}/portfolio", params={"month": "2026-11"}))["analysis_trends"]
        self.assertFalse(again["summary"]["stale"])
        self.assertEqual((again["topics"], again["days"], again["levels"]), (made["topics"], made["days"], made["levels"]))

        # 새 답장이 정리되면 낡은 것으로 보인다
        self.fake.clova = [dict(CALM, summary="오늘도 잘 지내신대요.")]
        self.assert_ok(self.text("month-reply-new", "오늘도 잘 지내"))
        self.run_jobs()
        self.assertTrue(self.assert_ok(self.client.get(f"/api/recipients/{rid}/portfolio", params={"month": "2026-11"}))["analysis_trends"]["summary"]["stale"])
        # 진단 같은 말이 나오면 seed 2로 한 번 더 하고, 그래도면 저장하지 않는다
        self.fake.clova = [{"summary": "우울증이 의심되는 한 달이었어요."}, {"summary": "치매 진단이 필요해 보여요."}]
        failed = self.client.post(f"/api/recipients/{rid}/portfolio/analysis-summary", params={"month": "2026-11"})
        self.assertEqual(failed.status_code, 502, failed.text)
        # 정리한 답장이 3개보다 적은 달은 만들지 않는다
        self.assertEqual(self.client.post(f"/api/recipients/{rid}/portfolio/analysis-summary", params={"month": "2026-10"}).status_code, 409)

        # 그 달의 답장을 지우면 저장한 정리도 지운다
        self.assert_ok(self.client.delete(f"/api/recipients/{rid}/replies/{ids['month-reply-1']}"))
        self.assertIsNone(self.assert_ok(self.client.get(f"/api/recipients/{rid}/portfolio", params={"month": "2026-11"}))["analysis_trends"]["summary"])
        # 분석을 끄면 이 칸이 아예 없다
        self.assert_ok(self.client.put(f"/api/recipients/{rid}/reply-analysis", json={"enabled": False}))
        self.assertNotIn("analysis_trends", self.assert_ok(self.client.get(f"/api/recipients/{rid}/portfolio", params={"month": "2026-11"})))
        with patch.object(settings, "reply_analysis_enabled", False):
            self.assertNotIn("analysis_trends", self.assert_ok(self.client.get(f"/api/recipients/{rid}/portfolio", params={"month": "2026-11"})))
            self.assertEqual(self.client.post(f"/api/recipients/{rid}/portfolio/analysis-summary").status_code, 404)

    def test_month_topics_cleaning_and_schema(self):
        clean, settle = reply_month._clean_topics, reply_month._settle
        calm3 = ["없음", "없음", "없음"]
        # 번호: 글자 숫자는 숫자로, 겹친 번호·참거짓·범위 밖은 뺀다. 이름은 앞뒤 빈칸을 지운다. 단계는 그 갈래 답장만
        self.assertEqual(clean([{"name": " 가족 ", "status": "평소 이야기", "replies": ["2", 1, 1, True, 7],
                                 "steps": [{"reply": 2, "label": " 손주 소식 "}, {"reply": 3, "label": "남의 답장"}, {"reply": 1, "label": ""}]}], calm3),
                         [{"name": "가족", "status": "평소 이야기", "replies": [1, 2], "steps": [{"reply": 2, "label": "손주 소식"}]}])
        # 같은 갈래가 두 번 오면 합치고, 답장이 많은 갈래부터 (같으면 건강·마음·외로움·생활·안전·가족·일상 순서)
        self.assertEqual([(t["name"], t["replies"]) for t in clean([
            {"name": "일상", "status": "평소 이야기", "replies": [1], "steps": []},
            {"name": "건강", "status": "이어지는 중", "replies": [2, 3], "steps": []},
            {"name": "일상", "status": "평소 이야기", "replies": [3, 4], "steps": []}], calm3 + ["없음"])], [("건강", [2, 3]), ("일상", [1, 4])])
        calm = {"name": "일상", "status": "평소 이야기", "steps": []}
        for broken in (None, "주제", [["목록"]], [dict(calm, replies="1")],     # 마지막 셋: 쓸 수 있는 갈래가 없다
                       [dict(calm, replies=[5])], [dict(calm, name="무릎 통증", replies=[1])], [dict(calm, name="", replies=[1])]):
            with self.assertRaises(ValueError):
                clean(broken, calm3)
        # 해결: {reply, by} 짝. reply는 살펴볼 일, by는 그 뒤의 평소 답장 (갈래는 보지 않는다).
        # by 뒤에 같은 신호가 다시 살펴볼 일로 나오면 끝나지 않은 것. 상태는 해결 목록과 맞춘다
        levels = ["바로 연락 필요", "없음", "살펴보기", "살펴보기", "없음", "살펴보기", "없음", "살펴보기", "없음"]
        knee, ankle = {("health", "아픔")}, {("health", "넘어짐·다침")}
        signals = [{("life", "사기 의심")}, set(), knee, knee, set(), knee, set(), ankle, set()]
        topics = [{"name": "생활·안전", "status": "이어지는 중", "replies": [1], "steps": []},        # 살펴볼 일 모두 해결 → 해결 완료
                  {"name": "건강", "status": "해결 완료", "replies": [3, 4, 6, 8], "steps": []},     # 남은 게 있는데 해결 완료 → 나아지는 중
                  {"name": "일상", "status": "이어지는 중", "replies": [2, 5, 7, 9], "steps": []}]   # 살펴볼 일 없음 → 평소 이야기
        pairs = [{"reply": 1, "by": 2},   # 받음: 해결 답장(2)은 다른 갈래(일상)여도 된다 (사기 전화 → "돈 안 보냈어")
                 {"reply": 3, "by": 4},   # 알려 준 답장이 아직 살펴보기 → 받지 않음
                 {"reply": 4, "by": 5},   # 5 뒤 6에서 같은 무릎 신호가 다시 살펴보기 → 끝나지 않은 일
                 {"reply": 6, "by": 9},   # 받음: 9 뒤에 무릎이 다시 나오지 않는다 (8 발목은 다른 일이고 9 앞이다)
                 {"reply": 8, "by": 7},   # 알려 준 답장이 앞 → 받지 않음
                 {"reply": 2, "by": 5},   # 2는 살펴볼 일이 아님 → 받지 않음
                 3, "x", {"reply": 99, "by": 100}]
        self.assertEqual(settle(topics, pairs, levels, signals), [1, 6])
        self.assertEqual([t["status"] for t in topics], ["해결 완료", "나아지는 중", "평소 이야기"])
        self.assertEqual(settle([{"name": "건강", "status": None, "replies": [3], "steps": []}], None, levels, signals), [])
        self.assertEqual(reply_month.SUMMARY_SCHEMA["properties"]["topics"]["items"]["properties"]["name"]["enum"], reply_month.CATEGORIES)
        self.assertEqual(reply_month.SUMMARY_SCHEMA["properties"]["topics"]["items"]["properties"]["status"]["enum"], reply_month.STATUSES)
        # 형식 강제가 지원하는 키워드만 쓴다 (test_reply_rules의 답장 판단 JSON 틀과 같은 기준)
        allowed = {"type", "enum", "items", "maxItems", "properties", "required"}

        def keywords(schema):
            for key, value in schema.items():
                yield key
                if key == "properties":
                    for sub in value.values():
                        yield from keywords(sub)
                elif isinstance(value, dict):
                    yield from keywords(value)
        self.assertLessEqual(set(keywords(reply_month.SUMMARY_SCHEMA)), allowed)

    def test_month_compare_voice_rows(self):
        from types import SimpleNamespace as A

        def voice(down=False, *slow):
            return {"status": "비교", "voice_down": down,
                    "items": [{"key": k, "state": "처짐" if k in slow else "비슷"} for k in reply_month.FEAT_ROWS]}
        prev_rows = [A(kind="voice", voice=voice(False, "rate"), voice_mismatch=False)]
        now_rows = [A(kind="voice", voice=voice(True, "rate", "loudness_db"), voice_mismatch=True),
                    A(kind="voice", voice=voice(False), voice_mismatch=False),
                    A(kind="voice", voice={"status": "기록 중"}, voice_mismatch=False),   # 평소 기록 중은 세지 않는다
                    A(kind="text", voice=None, voice_mismatch=False)]
        base = {"replies": 4, "voice": 3, "check": 1, "urgent": 0}
        now = {**base, **reply_month._voice_tally(now_rows, now_rows)}
        prev = {**base, "replies": 1, "voice": 1, **reply_month._voice_tally(prev_rows, prev_rows)}
        rows = reply_month._compare_rows(now, prev)
        self.assertEqual([(r["group"], r["label"], r["prev"], r["now"]) for r in rows if r["group"] == "목소리"],
                         [("목소리", "평소보다 처진 답장", 0, 1), ("목소리", "말과 목소리가 다른 답장", 0, 1),
                          ("목소리", "말이 느려진 답장", 1, 1), ("목소리", "목소리가 작아진 답장", 0, 1)])  # 두 달 다 0인 항목은 뺀다
        # 두 달 모두 평소 목소리와 비교한 음성 답장이 없으면 목소리 줄도 없다
        empty = {**base, **reply_month._voice_tally([], [])}
        self.assertEqual({r["group"] for r in reply_month._compare_rows(empty, empty)}, {"답장"})


if __name__ == "__main__":
    unittest.main()
