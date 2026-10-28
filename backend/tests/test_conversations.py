"""Conversation integration tests; all database and media writes use a temporary directory.

Run from the repository root:
    python -m unittest discover -s backend/tests -v
"""

import logging
import threading
import unittest
from contextlib import ExitStack, contextmanager
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from unittest.mock import patch


from _test_support import TEST_ROOT as _TEST_ROOT, app, db, settings, using_isolated_database
from fastapi.testclient import TestClient
from sqlalchemy import MetaData, func, inspect, select
from app.models import (
    Consent, Message, MonthlyPortfolio, Notification, ParentProfile,
    Recipient, SeniorReply, ShareLink, User,
)
from app.services import conversations, storage


NOW = datetime(2026, 10, 26, 3, 0, 0)
logging.getLogger("httpx").setLevel(logging.WARNING)


class ConversationIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.dev_login = patch.object(settings, "dev_login", True)
        self.dev_login.start()
        self.addCleanup(self.dev_login.stop)
        self.assertEqual(settings.data_dir, _TEST_ROOT)
        self.assertTrue(using_isolated_database(), str(db.engine.url))
        db.Base.metadata.drop_all(db.engine)
        db.init_db()
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    @contextmanager
    def clock(self, now=NOW):
        with ExitStack() as stack:
            for target in (
                "app.services.conversations.utcnow",
                "app.routers.watch.utcnow",
                "app.routers.messages.utcnow",
            ):
                stack.enter_context(patch(target, return_value=now))
            yield

    def assert_ok(self, response, status=200):
        self.assertEqual(response.status_code, status, response.text)
        return response.json()

    def login(self, name="owner"):
        self.assert_ok(self.client.post("/api/auth/dev-login", json={"name": name}))
        return self.assert_ok(self.client.get("/api/me"))["user"]["id"]

    def owner(self, name="owner", nickname="엄마"):
        uid = self.login(name)
        self.assert_ok(self.client.post("/api/consent", json={
            "voice": True, "face": True, "parent_receive": True,
        }))
        self.assert_ok(self.client.put("/api/parent", json={
            "nickname": nickname, "relation": "어머니", "phone": "01012345678",
            "child_call_name": "민수", "speech_level": "존댓말",
        }))
        recipients = self.assert_ok(self.client.get("/api/recipients"))
        self.assertEqual(len(recipients), 1)
        return uid, recipients[0]["id"]

    def recipient(self, nickname="아빠"):
        result = self.client.post("/api/recipients", json={
            "nickname": nickname, "relation": "아버지", "phone": "",
            "child_call_name": "민수",
        })
        self.assertIn(result.status_code, (200, 201), result.text)
        return result.json()["id"]

    def message(self, uid, rid, *, status="approved", created_at=NOW,
                approved_at=None, token=None, expires_at=None, revoked=False,
                script="건강히 지내세요."):
        with db.SessionLocal() as session:
            parent = session.scalar(select(ParentProfile).where(ParentProfile.user_id == uid))
            item = Message(
                user_id=uid, parent_id=parent.id, recipient_id=rid,
                memo="private owner memo", template="greeting", script=script,
                status=status, created_at=created_at,
                approved_at=approved_at or (created_at if status in ("approved", "sent", "viewed") else None),
                duration=3.5, captions=[],
            )
            session.add(item)
            session.flush()
            media = storage.message_dir(uid, item.id)
            for filename, field in (("video.mp4", "video_path"), ("poster.jpg", "poster_path")):
                path = media / filename
                path.write_bytes(b"isolated test media")
                setattr(item, field, storage.rel_path(path))
            if token:
                session.add(ShareLink(
                    message_id=item.id, token=token, revoked=revoked,
                    expires_at=expires_at or NOW + timedelta(days=1000),
                ))
            session.commit()
            return item.id

    def reply(self, uid, rid, text_value, created_at, client_id):
        with db.SessionLocal() as session:
            item = SeniorReply(
                user_id=uid, recipient_id=rid, text=text_value,
                created_at=created_at, client_id=client_id,
            )
            session.add(item)
            session.commit()
            return item.id

    def room(self, rid, date="2026-10-26", **params):
        return self.assert_ok(self.client.get(f"/api/conversations/{rid}", params={"date": date, **params}))

    def public_room(self, token="room-token", date="2026-10-26", **params):
        return self.assert_ok(self.client.get(f"/api/watch/{token}/conversation", params={"date": date, **params}))

    def test_legacy_parent_and_messages_backfill_is_idempotent(self):
        with db.SessionLocal() as session:
            owner = User(name="legacy", kakao_id="dev:legacy")
            session.add(owner)
            session.flush()
            parent = ParentProfile(
                user_id=owner.id, nickname="할머니", relation="할머니",
                phone="010-1234-5678", child_call_name="손주", speech_level="존댓말",
            )
            session.add(parent)
            session.flush()
            message = Message(
                user_id=owner.id, parent_id=parent.id, memo="legacy", template="greeting",
                script="할머니 안녕하세요.", status="approved", created_at=NOW, approved_at=NOW,
            )
            session.add(message)
            session.flush()
            session.add(ShareLink(message_id=message.id, token="legacy-token", expires_at=NOW + timedelta(days=2)))
            session.commit()
            uid, mid, parent_id = owner.id, message.id, parent.id
        db.init_db()
        db.init_db()
        with db.SessionLocal() as session:
            recipients = session.scalars(select(Recipient).where(Recipient.user_id == uid)).all()
            self.assertEqual(len(recipients), 1)
            self.assertEqual(recipients[0].legacy_parent_id, parent_id)
            self.assertEqual(recipients[0].nickname, "할머니")
            self.assertEqual(session.get(Message, mid).recipient_id, recipients[0].id)
        with self.clock():
            self.assertEqual(self.public_room("legacy-token")["recipient"]["nickname"], "할머니")

    def test_existing_sqlite_schema_is_migrated_without_replacing_old_rows(self):
        # Recreate the pre-feature tables, including the genuinely absent new
        # columns, to exercise ALTER TABLE and creation of the new indexes.
        db.Base.metadata.drop_all(db.engine)
        legacy = MetaData()
        for name in ("users", "parent_profiles", "messages", "share_links", "notifications"):
            table = db.Base.metadata.tables[name].to_metadata(legacy)
            if "recipient_id" in table.c:
                column = table.c.recipient_id
                for constraint in list(table.constraints):
                    if "recipient_id" in constraint.columns:
                        table.constraints.remove(constraint)
                for index in list(table.indexes):
                    if "recipient_id" in index.columns:
                        table.indexes.remove(index)
                for foreign_key in list(column.foreign_keys):
                    table.foreign_keys.discard(foreign_key)
                table._columns.remove(column)
        legacy.create_all(db.engine)
        with db.engine.begin() as connection:
            connection.execute(legacy.tables["users"].insert().values(id=41, name="legacy", kakao_id="dev:legacy"))
            connection.execute(legacy.tables["parent_profiles"].insert().values(
                id=51, user_id=41, nickname="외할머니", relation="할머니", phone="010-1234-5678",
            ))
            connection.execute(legacy.tables["messages"].insert().values(
                id=61, user_id=41, parent_id=51, memo="old memo", template="greeting",
                script="옛날 편지", status="approved", approved_at=NOW, created_at=NOW,
            ))
            connection.execute(legacy.tables["share_links"].insert().values(
                id=71, message_id=61, token="preserved-token", expires_at=NOW + timedelta(days=2),
            ))
            connection.execute(legacy.tables["notifications"].insert().values(
                id=81, user_id=41, message_id=61, kind="viewed", text="old notification",
            ))
        self.assertNotIn("recipient_id", {c["name"] for c in inspect(db.engine).get_columns("messages")})
        db.init_db()
        db.init_db()
        with db.SessionLocal() as session:
            recipient = session.scalar(select(Recipient).where(Recipient.legacy_parent_id == 51))
            self.assertIsNotNone(recipient)
            self.assertEqual(session.get(Message, 61).recipient_id, recipient.id)
            self.assertEqual(session.get(Message, 61).script, "옛날 편지")
            self.assertEqual(session.get(ShareLink, 71).token, "preserved-token")
            self.assertEqual(session.get(Notification, 81).text, "old notification")
            self.assertEqual(session.scalar(select(func.count()).select_from(Recipient)), 1)
        self.assertIn("recipient_id", {c["name"] for c in inspect(db.engine).get_columns("notifications")})

    def test_multiple_recipients_and_cross_user_routes_are_isolated(self):
        uid, first = self.owner()
        second = self.recipient()
        other_uid, other = self.owner("another-owner", "다른 엄마")
        self.message(uid, first, token="room-token")
        self.message(uid, second, token="second-token")
        secret = self.message(other_uid, other, token="other-token")
        self.login()
        with self.clock():
            self.assertEqual({r["id"] for r in self.assert_ok(self.client.get("/api/recipients"))}, {first, second})
            for method, path, kwargs in (
                ("get", f"/api/recipients/{other}", {}),
                ("put", f"/api/recipients/{other}", {"json": {"nickname": "hijack", "relation": "friend"}}),
                ("get", f"/api/conversations/{other}", {}),
                ("get", f"/api/recipients/{other}/portfolio?month=2026-10", {}),
                ("post", f"/api/recipients/{other}/portfolio?month=2026-10", {}),
                ("get", f"/api/messages/{secret}", {}),
            ):
                with self.subTest(path=path, method=method):
                    self.assertEqual(getattr(self.client, method)(path, **kwargs).status_code, 404)
            self.assertEqual({e["message"]["recipient_id"] for e in self.room(first)["events"] if e["type"] == "video"}, {first})
        self.client.cookies.clear()
        self.assertEqual(self.client.get("/api/recipients").status_code, 401)
        self.assertEqual(self.client.get(f"/api/conversations/{first}").status_code, 401)

    def test_primary_profile_sync_and_recipient_validation_preserve_other_contacts(self):
        _uid, rid = self.owner()
        second = self.recipient()
        self.assert_ok(self.client.put(f"/api/recipients/{rid}", json={
            "nickname": "어머니", "relation": "엄마", "phone": "01098765432",
            "child_call_name": "우리 아들", "speech_level": "반말", "tone_examples": "밥 먹었어?",
        }))
        parent = self.assert_ok(self.client.get("/api/parent"))
        self.assertEqual(parent["nickname"], "어머니")
        self.assertEqual(parent["phone"], "010-9876-5432")
        self.assert_ok(self.client.put("/api/parent", json={
            "nickname": "엄마", "relation": "어머니", "phone": "01012345678",
            "child_call_name": "민수",
        }))
        self.assertEqual(self.assert_ok(self.client.get(f"/api/recipients/{rid}"))["nickname"], "엄마")
        self.assertEqual(self.assert_ok(self.client.get(f"/api/recipients/{second}"))["nickname"], "아빠")
        for payload in ({"nickname": "   ", "relation": "어머니"},
                        {"nickname": "엄마", "relation": "  "},
                        {"nickname": "엄마", "relation": "어머니", "phone": "123"}):
            self.assertEqual(self.client.post("/api/recipients", json=payload).status_code, 422)

    def test_message_generation_uses_selected_recipient_and_approval_adds_it_to_room(self):
        uid, primary = self.owner()
        chosen = self.recipient()
        _other_uid, foreign = self.owner("another-owner", "다른 엄마")
        self.login()
        candidates = [{"style": "warm", "label": "따뜻하게", "script": "아빠 안녕하세요. 오늘 산책을 다녀왔어요. 건강하게 지내세요.", "source": "fallback"}]
        with self.clock(), patch("app.routers.messages.script_llm.generate_candidates", return_value=candidates) as generate:
            created = self.assert_ok(self.client.post("/api/messages", json={
                "memo": "오늘 산책", "recipient_id": chosen,
            }))
            self.assertEqual(created["recipient_id"], chosen)
            self.assertEqual(created["parent_nickname"], "아빠")
            self.assertEqual(generate.call_args.args[2], "아빠")
            self.assertEqual(self.client.post("/api/messages", json={"memo": "wrong owner", "recipient_id": foreign}).status_code, 404)
            default = self.assert_ok(self.client.post("/api/messages", json={"memo": "기본 대상자"}))
            self.assertEqual(default["recipient_id"], primary)
            with db.SessionLocal() as session:
                draft = session.get(Message, created["id"])
                draft.status = "ready"
                draft.video_path = storage.rel_path(storage.message_dir(uid, draft.id) / "video.mp4")
                storage.abs_path(draft.video_path).write_bytes(b"approved test media")
                session.commit()
            approved = self.assert_ok(self.client.post(f"/api/messages/{created['id']}/approve"))
            token = approved["share"]["url"].rsplit("/", 1)[1]
            public = self.public_room(token)
            self.assertEqual([e["id"] for e in public["events"] if e["type"] == "video"], [created["id"]])
            self.assertEqual(self.room(primary)["recipient"]["id"], primary)

    def test_old_link_opens_current_room_and_hides_drafts_and_private_fields(self):
        uid, rid = self.owner()
        other = self.recipient()
        old = self.message(uid, rid, created_at=NOW - timedelta(days=1), token="room-token")
        current = self.message(uid, rid, token="new-token")
        draft = self.message(uid, rid, status="draft")
        ready = self.message(uid, rid, status="ready")
        other_id = self.message(uid, other, token="second-token")
        self.reply(uid, rid, "잘 봤어", NOW + timedelta(minutes=1), "first-reply")
        self.client.cookies.clear()
        with self.clock():
            info = self.public_room()
            videos = [e["message"] for e in info["events"] if e["type"] == "video"]
            self.assertEqual([m["id"] for m in videos], [current])
            yesterday = self.public_room(date="2026-10-25")
            self.assertEqual([e["id"] for e in yesterday["events"] if e["type"] == "video"], [old])
            public_text = str(info)
            for private in ("private owner memo", "010-1234-5678", "audio_url", "tone_examples", "session_secret"):
                self.assertNotIn(private, public_text)
            for mid, expected in ((current, 200), (draft, 404), (ready, 404), (other_id, 404)):
                for kind in ("video", "poster"):
                    response = self.client.get(f"/api/watch/room-token/messages/{mid}/{kind}")
                    self.assertEqual(response.status_code, expected, response.text)

    def test_revoked_expired_and_deleted_links_reject_all_public_operations(self):
        uid, rid = self.owner()
        active = self.message(uid, rid, token="room-token")
        cases = (("revoked-token", True, NOW + timedelta(days=1), "approved"),
                 ("expired-token", False, NOW - timedelta(seconds=1), "approved"),
                 ("deleted-token", False, NOW + timedelta(days=1), "deleted"))
        for token, revoked, expires_at, status in cases:
            mid = self.message(uid, rid, token=token, revoked=revoked, expires_at=expires_at, status=status)
            with self.clock(), self.subTest(token=token):
                for suffix in ("", "/conversation", "/video", "/poster", f"/messages/{active}/video", f"/messages/{mid}/poster"):
                    response = self.client.get(f"/api/watch/{token}{suffix}")
                    self.assertEqual(response.status_code, 410, response.text)
                response = self.client.post(f"/api/watch/{token}/replies", json={"text": "접근 불가", "client_id": "invalid-link-reply"})
                self.assertEqual(response.status_code, 410, response.text)
                self.assertEqual(self.client.post(f"/api/watch/{token}/viewed").status_code, 410)
        with db.SessionLocal() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(SeniorReply)), 0)

    def test_reply_persists_once_and_cross_room_or_blank_input_is_rejected(self):
        uid, rid = self.owner()
        second = self.recipient()
        mid = self.message(uid, rid, token="room-token")
        alien = self.message(uid, second, token="second-token")
        self.client.cookies.clear()
        payload = {"text": "  오늘 산책해서 기분이 좋아.  ", "client_id": "stable-client-id", "message_id": mid}
        with self.clock():
            first = self.assert_ok(self.client.post("/api/watch/room-token/replies", json=payload))
            again = self.assert_ok(self.client.post("/api/watch/room-token/replies", json=payload))
            self.assertEqual(first["id"], again["id"])
            self.assertEqual(first["text"], payload["text"].strip())
            room = self.public_room()
            self.assertEqual(len([e for e in room["events"] if e["type"] == "reply"]), 1)
            for bad in ("", "   ", "\n\t"):
                response = self.client.post("/api/watch/room-token/replies", json={"text": bad, "client_id": "blank-reply-id"})
                self.assertEqual(response.status_code, 422, response.text)
            response = self.client.post("/api/watch/room-token/replies", json={"text": "wrong video", "client_id": "wrong-room-reply", "message_id": alien})
            self.assertEqual(response.status_code, 404, response.text)
            self.assertEqual(self.client.post("/api/watch/room-token/replies", json={"text": "wrong", "client_id": "invalid spaces"}).status_code, 422)
        with db.SessionLocal() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(SeniorReply)), 1)
            notes = session.scalars(select(Notification).where(Notification.kind == "senior_reply")).all()
            self.assertEqual(len(notes), 1)
            self.assertEqual(notes[0].user_id, uid)
            self.assertEqual(notes[0].recipient_id, rid)
        self.login()
        with self.clock():
            self.assertEqual([e["text"] for e in self.room(rid)["events"] if e["type"] == "reply"], [payload["text"].strip()])

    def test_idempotent_reply_retry_still_requires_an_active_link(self):
        uid, rid = self.owner()
        mid = self.message(uid, rid, token="room-token")
        payload = {"text": "한 번만 저장", "client_id": "retry-client-id", "message_id": mid}
        with self.clock():
            self.assert_ok(self.client.post("/api/watch/room-token/replies", json=payload))
            with db.SessionLocal() as session:
                link = session.scalar(select(ShareLink).where(ShareLink.token == "room-token"))
                link.revoked = True
                session.commit()
            self.assertEqual(self.client.post("/api/watch/room-token/replies", json=payload).status_code, 410)

    def test_reply_idempotency_is_per_recipient_and_conflicting_retries_fail(self):
        uid, rid = self.owner()
        second = self.recipient()
        self.message(uid, rid, token="room-token")
        self.message(uid, rid, token="new-token")
        self.message(uid, second, token="second-token")
        payload = {"text": "같은 기기에서 보냄", "client_id": "same-device-client"}
        with self.clock():
            first = self.assert_ok(self.client.post("/api/watch/room-token/replies", json=payload))
            retry = self.assert_ok(self.client.post("/api/watch/new-token/replies", json=payload))
            self.assertEqual(first["id"], retry["id"])
            conflict = self.client.post("/api/watch/room-token/replies", json={**payload, "text": "바뀐 내용"})
            self.assertEqual(conflict.status_code, 409, conflict.text)
            other = self.assert_ok(self.client.post("/api/watch/second-token/replies", json=payload))
            self.assertNotEqual(first["id"], other["id"])

    def test_concurrent_reply_retries_create_one_reply_and_one_notification(self):
        uid, rid = self.owner()
        self.message(uid, rid, token="room-token")
        self.client.cookies.clear()
        payload = {"text": "동시에 재시도한 답글", "client_id": "concurrent-client-id"}
        with self.clock(), ThreadPoolExecutor(max_workers=6) as executor:
            responses = list(executor.map(
                lambda _index: self.client.post("/api/watch/room-token/replies", json=payload), range(6),
            ))
        data = [self.assert_ok(response) for response in responses]
        self.assertEqual(len({item["id"] for item in data}), 1)
        with db.SessionLocal() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(SeniorReply)), 1)
            self.assertEqual(session.scalar(select(func.count()).select_from(Notification).where(Notification.kind == "senior_reply")), 1)

    def test_viewed_endpoint_targets_the_played_video_and_public_responses_are_private(self):
        uid, rid = self.owner()
        second = self.recipient()
        original = self.message(uid, rid, token="room-token")
        played = self.message(uid, rid, token="new-token")
        foreign = self.message(uid, second, token="second-token")
        with self.clock():
            for _ in range(2):
                self.assert_ok(self.client.post(f"/api/watch/room-token/messages/{played}/viewed"))
            self.assertEqual(self.client.post(f"/api/watch/room-token/messages/{foreign}/viewed").status_code, 404)
            for path in ("/api/watch/room-token", "/api/watch/room-token/conversation",
                         f"/api/watch/room-token/messages/{played}/video"):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertIn("no-store", response.headers["cache-control"])
                self.assertEqual(response.headers["referrer-policy"], "no-referrer")
        with db.SessionLocal() as session:
            self.assertIsNotNone(session.get(Message, played).viewed_at)
            self.assertIsNone(session.get(Message, original).viewed_at)
            self.assertIsNone(session.get(Message, foreign).viewed_at)
            notes = session.scalars(select(Notification).where(Notification.kind == "viewed")).all()
            self.assertEqual(len(notes), 1)
            self.assertEqual(notes[0].message_id, played)
            self.assertEqual(notes[0].recipient_id, rid)
            anchor_link = session.scalar(select(ShareLink).where(ShareLink.message_id == original))
            played_link = session.scalar(select(ShareLink).where(ShareLink.message_id == played))
            self.assertEqual(anchor_link.view_count, 0)
            self.assertIsNone(anchor_link.first_viewed_at)
            self.assertEqual(played_link.view_count, 2)
            self.assertIsNotNone(played_link.first_viewed_at)

    def test_reply_rate_limit_does_not_block_idempotent_retry(self):
        uid, rid = self.owner()
        self.message(uid, rid, token="room-token")
        first_payload = {"text": "첫 답글", "client_id": "rate-limit-first"}
        with self.clock():
            first = self.assert_ok(self.client.post("/api/watch/room-token/replies", json=first_payload))
            limited = None
            for index in range(40):
                limited = self.client.post("/api/watch/room-token/replies", json={"text": f"reply {index}", "client_id": f"rate-limit-{index:04d}"})
                if limited.status_code == 429:
                    break
                self.assertEqual(limited.status_code, 200, limited.text)
            self.assertEqual(limited.status_code, 429, "A bearer link must have a bounded reply rate")
            self.assertEqual(self.assert_ok(self.client.post("/api/watch/room-token/replies", json=first_payload))["id"], first["id"])

    def test_kst_midnight_rollover_creates_new_day_and_preserves_archive(self):
        uid, rid = self.owner()
        before = datetime(2026, 10, 26, 14, 59, 59)
        after = datetime(2026, 10, 26, 15, 0, 0)
        self.message(uid, rid, created_at=before - timedelta(minutes=1), token="room-token")
        with self.clock(before):
            old_reply = self.assert_ok(self.client.post("/api/watch/room-token/replies", json={"text": "자정 전", "client_id": "before-midnight"}))
            info = self.public_room()
            self.assertEqual(info["today"], "2026-10-26")
            self.assertEqual(old_reply["date"], "2026-10-26")
        with self.clock(after):
            new_reply = self.assert_ok(self.client.post("/api/watch/room-token/replies", json={"text": "자정 후", "client_id": "after-midnight"}))
            info = self.assert_ok(self.client.get("/api/watch/room-token/conversation"))
            self.assertEqual(info["today"], "2026-10-27")
            self.assertEqual(info["selected_date"], "2026-10-27")
            self.assertEqual(new_reply["date"], "2026-10-27")
            self.assertEqual([e["text"] for e in info["events"] if e["type"] == "reply"], ["자정 후"])
            archive = self.public_room(date="2026-10-26")
            self.assertEqual([e["text"] for e in archive["events"] if e["type"] == "reply"], ["자정 전"])
            self.assertEqual({d["date"] for d in info["days"]}, {"2026-10-26", "2026-10-27"})
            self.assertEqual(self.room(rid, date="2026-10-27")["events"], info["events"])

    def test_events_are_chronological_and_pagination_has_no_loss_or_duplicates(self):
        uid, rid = self.owner()
        first = self.message(uid, rid, created_at=NOW, token="room-token")
        # Matching timestamps test that the cursor includes event type and id,
        # rather than dropping one of two events at a page boundary.
        self.reply(uid, rid, "first reply", NOW, "pagination-first")
        self.message(uid, rid, created_at=NOW + timedelta(seconds=1), token="new-token")
        self.reply(uid, rid, "second reply", NOW + timedelta(seconds=1), "pagination-second")
        self.reply(uid, rid, "last reply", NOW + timedelta(seconds=2), "pagination-last")
        with self.clock():
            expected = self.public_room()["events"]
            self.assertEqual([e["created_at"] for e in expected], sorted(e["created_at"] for e in expected))
            all_events = []
            before = None
            for _ in range(10):
                params = {"limit": 2, **({"before": before} if before else {})}
                page = self.public_room(**params)
                self.assertEqual([e["created_at"] for e in page["events"]], sorted(e["created_at"] for e in page["events"]))
                all_events[0:0] = page["events"]
                if not page["has_more"]:
                    break
                self.assertTrue(page["next_before"])
                self.assertNotEqual(before, page["next_before"])
                before = page["next_before"]
            self.assertEqual([(e["type"], e["id"]) for e in all_events], [(e["type"], e["id"]) for e in expected])
            self.assertIn(first, [e["id"] for e in expected if e["type"] == "video"])
            self.assertEqual(self.client.get(f"/api/conversations/{rid}?date=2026-02-31").status_code, 422)
            self.assertEqual(self.client.get(f"/api/conversations/{rid}?before=broken-cursor").status_code, 422)

    def test_fractional_event_timestamps_sort_and_paginate_in_actual_time_order(self):
        uid, rid = self.owner()
        exact = self.message(uid, rid, token="room-token")
        micro = self.reply(uid, rid, "one microsecond later", NOW + timedelta(microseconds=1), "fractional-first")
        milli = self.message(uid, rid, created_at=NOW + timedelta(milliseconds=1), token="millisecond-token")
        almost_second = self.reply(uid, rid, "just before next second", NOW + timedelta(microseconds=999999), "fractional-second")
        second = self.message(uid, rid, created_at=NOW + timedelta(seconds=1), token="next-second-token")
        expected = [("video", exact), ("reply", micro), ("video", milli),
                    ("reply", almost_second), ("video", second)]
        with self.clock():
            self.assertEqual([(e["type"], e["id"]) for e in self.public_room()["events"]], expected)
            actual = []
            cursor = None
            for _ in range(len(expected)):
                page = self.public_room(limit=1, **({"before": cursor} if cursor else {}))
                self.assertEqual(len(page["events"]), 1)
                actual[0:0] = [(e["type"], e["id"]) for e in page["events"]]
                cursor = page["next_before"]
                if not page["has_more"]:
                    break
            self.assertEqual(actual, expected)

    def test_submillisecond_midnight_boundaries_match_day_and_month_indexes(self):
        uid, rid = self.owner()
        before = datetime(2026, 10, 31, 14, 59, 59, 999999)
        after = datetime(2026, 10, 31, 15, 0, 0)
        self.message(uid, rid, created_at=before, token="room-token")
        self.reply(uid, rid, "10월 마지막 순간", before, "submillisecond-before")
        self.reply(uid, rid, "11월 첫 순간", after, "submillisecond-after")
        with self.clock(after):
            previous_day = self.public_room(date="2026-10-31")
            self.assertEqual([(e["type"], e["date"]) for e in previous_day["events"]],
                             [("reply", "2026-10-31"), ("video", "2026-10-31")])
            counts = {day["date"]: (day["video_count"], day["reply_count"]) for day in previous_day["days"]}
            self.assertEqual(counts, {"2026-10-31": (1, 1), "2026-11-01": (0, 1)})
            overview = self.assert_ok(self.client.get(f"/api/recipients/{rid}"))
            self.assertEqual(overview["today_reply_count"], 1)
            self.assertEqual(overview["today_video_count"], 0)
            october = self.assert_ok(self.client.get(f"/api/recipients/{rid}/portfolio?month=2026-10"))
            self.assertEqual(october["reply_count"], 1)

    def test_monthly_portfolio_uses_kst_boundaries_evidence_and_recipient_scope(self):
        uid, rid = self.owner()
        second = self.recipient()
        self.reply(uid, rid, "9월에만 있는 답글", datetime(2026, 9, 30, 14, 59, 59), "outside-before")
        first = self.reply(uid, rid, "오늘 산책해서 즐거웠어", datetime(2026, 9, 30, 15, 0, 0), "inside-first")
        last = self.reply(uid, rid, "가족과 밥 먹어서 좋아", datetime(2026, 10, 31, 14, 59, 59), "inside-last")
        self.reply(uid, rid, "11월에만 있는 답글", datetime(2026, 10, 31, 15, 0, 0), "outside-after")
        self.reply(uid, second, "다른 대상자의 비밀", datetime(2026, 10, 15, 3), "other-recipient")
        path = f"/api/recipients/{rid}/portfolio?month=2026-10"
        with self.clock(datetime(2026, 11, 2)):
            empty = self.assert_ok(self.client.get(path))
            self.assertEqual(empty["reply_count"], 2)
            self.assertIsNone(empty["portfolio"])
            data = self.assert_ok(self.client.post(path))
            self.assertEqual(data["month"], "2026-10")
            self.assertEqual(data["recipient_id"], rid)
            self.assertEqual(data["reply_count"], 2)
            self.assertEqual(data["active_days"], 2)
            report = data["portfolio"]
            self.assertEqual(report["reply_count"], 2)
            self.assertEqual(report["days_in_month"], 31)
            self.assertEqual({r["reply_id"] for r in report["representative_replies"]}, {first, last})
            self.assertEqual({d["date"] for d in report["daily_trends"]}, {"2026-10-01", "2026-10-31"})
            rendered = str(report)
            for unrelated in ("9월에만", "11월에만", "다른 대상자의 비밀"):
                self.assertNotIn(unrelated, rendered)
            self.assertTrue(report["caveats"])
            self.assertFalse(data["stale"])
            self.assertEqual(self.assert_ok(self.client.get(path))["portfolio"]["id"], report["id"])

    def test_portfolio_fingerprint_detects_new_or_changed_replies(self):
        uid, rid = self.owner()
        reply_id = self.reply(uid, rid, "산책이 좋아", NOW, "portfolio-first")
        path = f"/api/recipients/{rid}/portfolio?month=2026-10"
        with self.clock():
            original = self.assert_ok(self.client.post(path))
            self.reply(uid, rid, "식사도 잘했어", NOW + timedelta(hours=1), "portfolio-second")
            stale = self.assert_ok(self.client.get(path))
            self.assertTrue(stale["stale"])
            self.assertEqual(stale["reply_count"], 2)
            fresh = self.assert_ok(self.client.post(path))
            self.assertFalse(fresh["stale"])
            self.assertEqual(fresh["portfolio"]["reply_count"], 2)
            with db.SessionLocal() as session:
                session.get(SeniorReply, reply_id).text = "같은 개수지만 내용이 바뀜"
                session.commit()
            self.assertTrue(self.assert_ok(self.client.get(path))["stale"])
            self.assertEqual(self.assert_ok(self.client.post(path))["portfolio"]["id"], original["portfolio"]["id"])
            self.assertEqual(self.client.post(f"/api/recipients/{rid}/portfolio?month=2026-09").status_code, 409)
            self.assertEqual(self.client.get(f"/api/recipients/{rid}/portfolio?month=2026-13").status_code, 422)
        with db.SessionLocal() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(MonthlyPortfolio)), 1)

    def test_worker_automatically_creates_and_refreshes_only_closed_kst_months(self):
        uid, rid = self.owner()
        second = self.recipient()
        # These two UTC dates straddle Korea's month boundary by one microsecond.
        self.reply(uid, rid, "지난달 마지막 답글", datetime(2026, 10, 31, 14, 59, 59, 999999), "automatic-october")
        self.reply(uid, rid, "이번달 답글", datetime(2026, 10, 31, 15), "automatic-november")
        self.reply(uid, second, "다른 대상자 지난달", datetime(2026, 10, 20), "automatic-other")
        with self.clock(datetime(2026, 11, 1, 0)):
            with db.SessionLocal() as session:
                self.assertEqual(conversations.refresh_closed_portfolios(session), 2)
                self.assertEqual(conversations.refresh_closed_portfolios(session), 0)
                rows = session.scalars(select(MonthlyPortfolio)).all()
                self.assertEqual({(row.recipient_id, row.month) for row in rows}, {(rid, "2026-10"), (second, "2026-10")})
                self.assertTrue(all(row.source_reply_count == 1 for row in rows))
            self.reply(uid, rid, "추가 복구한 지난달 답글", datetime(2026, 10, 25), "automatic-late-reply")
            with db.SessionLocal() as session:
                self.assertEqual(conversations.refresh_closed_portfolios(session), 1)
                self.assertEqual(conversations.refresh_closed_portfolios(session), 0)
            october = self.assert_ok(self.client.get(f"/api/recipients/{rid}/portfolio?month=2026-10"))
            self.assertFalse(october["stale"])
            self.assertEqual(october["portfolio"]["reply_count"], 2)
            self.assertIsNone(self.assert_ok(self.client.get(f"/api/recipients/{rid}/portfolio?month=2026-11"))["portfolio"])

    def test_consent_withdrawal_removes_replies_reports_and_public_access_for_only_owner(self):
        uid, rid = self.owner()
        mid = self.message(uid, rid, token="room-token")
        self.reply(uid, rid, "내 답글", NOW, "withdrawn-reply")
        with self.clock():
            self.assert_ok(self.client.post(f"/api/recipients/{rid}/portfolio?month=2026-10"))
        other_uid, other_rid = self.owner("another-owner", "다른 엄마")
        other_mid = self.message(other_uid, other_rid, token="other-token")
        self.reply(other_uid, other_rid, "보존되는 다른 답글", NOW, "preserved-reply")
        self.login()
        with self.clock():
            self.assert_ok(self.client.post("/api/consent/withdraw"))
            self.assertEqual(self.client.get("/api/watch/room-token/conversation").status_code, 410)
            self.assertEqual(self.client.post("/api/watch/room-token/replies", json={"text": "차단", "client_id": "withdrawal-blocked"}).status_code, 410)
            self.assertEqual(self.client.get(f"/api/watch/room-token/messages/{mid}/video").status_code, 410)
            self.assertEqual(self.client.get(f"/api/watch/other-token/messages/{other_mid}/video").status_code, 200)
        with db.SessionLocal() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(SeniorReply).where(SeniorReply.user_id == uid)), 0)
            self.assertEqual(session.scalar(select(func.count()).select_from(MonthlyPortfolio).where(MonthlyPortfolio.user_id == uid)), 0)
            self.assertEqual(session.scalar(select(func.count()).select_from(SeniorReply).where(SeniorReply.user_id == other_uid)), 1)
            self.assertEqual(session.get(Message, mid).status, "deleted")
            self.assertTrue(all(c.withdrawn_at for c in session.scalars(select(Consent).where(Consent.user_id == uid))))

    def test_concurrent_withdrawal_cannot_leave_late_replies_or_portfolios(self):
        for write_kind in ("reply", "portfolio"):
            with self.subTest(write_kind=write_kind):
                uid, rid = self.owner("race-" + write_kind)
                self.message(uid, rid, token="race-token-" + write_kind)
                self.reply(uid, rid, "철회하면 삭제될 답글", NOW, "race-source-" + write_kind)
                write_paused = threading.Event()
                allow_write = threading.Event()
                cleanup_reached = threading.Event()
                if write_kind == "reply":
                    target = "app.services.conversations.day_bounds"
                    original = conversations.day_bounds
                    path = "/api/watch/race-token-reply/replies"
                    payload = {"text": "동시에 도착한 답글", "client_id": "withdrawal-race-reply"}
                else:
                    target = "app.services.conversations.build_portfolio"
                    original = conversations.build_portfolio
                    path = f"/api/recipients/{rid}/portfolio?month=2026-10"
                    payload = None
                original_user_dir = storage.user_dir

                def pause_write(*args, **kwargs):
                    write_paused.set()
                    if not allow_write.wait(10):
                        raise AssertionError("Timed out waiting to release the pending write")
                    return original(*args, **kwargs)

                def mark_cleanup(*args, **kwargs):
                    cleanup_reached.set()
                    return original_user_dir(*args, **kwargs)

                with self.clock(), patch(target, side_effect=pause_write), \
                        patch("app.routers.account.storage.user_dir", side_effect=mark_cleanup), \
                        ThreadPoolExecutor(max_workers=2) as executor:
                    pending = executor.submit(self.client.post, path, **({"json": payload} if payload else {}))
                    try:
                        self.assertTrue(write_paused.wait(5), "Write did not reach the controlled race point")
                        withdrawing = executor.submit(self.client.post, "/api/consent/withdraw")
                        # Without a real transaction lock, withdrawal can commit
                        # while this earlier request still holds validated data.
                        if cleanup_reached.wait(0.25):
                            self.assert_ok(withdrawing.result(timeout=5))
                    finally:
                        allow_write.set()
                    self.assert_ok(pending.result(timeout=5))
                    self.assert_ok(withdrawing.result(timeout=5))
                with db.SessionLocal() as session:
                    self.assertEqual(session.scalar(select(func.count()).select_from(SeniorReply).where(SeniorReply.user_id == uid)), 0)
                    self.assertEqual(session.scalar(select(func.count()).select_from(MonthlyPortfolio).where(MonthlyPortfolio.user_id == uid)), 0)
                    self.assertEqual(session.scalar(select(func.count()).select_from(Notification).where(
                        Notification.user_id == uid, Notification.kind == "senior_reply",
                    )), 0)

    def test_viewing_request_validated_before_withdrawal_cannot_restore_deleted_video(self):
        from app.routers import watch

        uid, rid = self.owner()
        mid = self.message(uid, rid, token="room-token")
        validated = threading.Event()
        resume = threading.Event()
        original = watch._link

        def pause_first_validation(*args, **kwargs):
            link = original(*args, **kwargs)
            if not validated.is_set():
                validated.set()
                if not resume.wait(10):
                    raise AssertionError("Timed out waiting for consent withdrawal")
            return link

        with self.clock(), patch("app.routers.watch._link", side_effect=pause_first_validation), \
                ThreadPoolExecutor(max_workers=1) as executor:
            pending = executor.submit(self.client.post, f"/api/watch/room-token/messages/{mid}/viewed")
            try:
                self.assertTrue(validated.wait(5))
                self.assert_ok(self.client.post("/api/consent/withdraw"))
            finally:
                resume.set()
            response = pending.result(timeout=5)
            self.assertEqual(response.status_code, 410, response.text)
        with db.SessionLocal() as session:
            self.assertEqual(session.get(Message, mid).status, "deleted")
            self.assertIsNone(session.get(Message, mid).viewed_at)
            self.assertEqual(session.scalar(select(func.count()).select_from(Notification).where(Notification.user_id == uid)), 0)

    def test_owner_deletes_one_video_letter_and_its_link_but_keeps_replies(self):
        uid, rid = self.owner()
        mid = self.message(uid, rid, token="room-token")
        kept = self.message(uid, rid, token="kept-token", created_at=NOW + timedelta(minutes=5))
        busy = self.message(uid, rid, status="generating", created_at=NOW + timedelta(minutes=10))
        self.client.cookies.clear()
        with self.clock():
            reply = self.assert_ok(self.client.post("/api/watch/room-token/replies", json={
                "text": "잘 봤어", "client_id": "reply-to-deleted", "message_id": mid,
            }))
        media = storage.message_dir(uid, mid)
        self.assertTrue((media / "video.mp4").exists())

        self.login("intruder")
        self.assertEqual(self.client.delete(f"/api/messages/{mid}").status_code, 404)
        self.login()
        self.assertEqual(self.client.delete(f"/api/messages/{busy}").status_code, 409)
        self.assert_ok(self.client.delete(f"/api/messages/{mid}"))
        self.assertEqual(self.client.delete(f"/api/messages/{mid}").status_code, 404)

        self.assertFalse(media.exists())
        with self.clock():
            events = self.room(rid)["events"]
            self.assertEqual([e["id"] for e in events if e["type"] == "video"], [kept, busy])
            self.assertEqual([(e["id"], e["message_id"]) for e in events if e["type"] == "reply"], [(reply["id"], None)])
            self.client.cookies.clear()
            self.assertEqual(self.client.get("/api/watch/room-token/conversation").status_code, 410)
            self.assertEqual(self.client.post(f"/api/watch/kept-token/messages/{mid}/viewed").status_code, 404)
            self.assertEqual([e["id"] for e in self.public_room("kept-token")["events"] if e["type"] == "video"], [kept])
        with db.SessionLocal() as session:
            deleted = session.get(Message, mid)
            self.assertEqual(deleted.status, "deleted")
            self.assertIsNone(deleted.video_path)
            self.assertTrue(session.scalar(select(ShareLink.revoked).where(ShareLink.message_id == mid)))
            self.assertFalse(session.scalar(select(ShareLink.revoked).where(ShareLink.message_id == kept)))

    def test_owner_deletes_one_reply_with_its_notification_and_report_quote(self):
        uid, rid = self.owner()
        second = self.recipient()
        self.message(uid, rid, token="room-token")
        self.message(uid, second, token="second-token")
        self.client.cookies.clear()
        with self.clock():
            gone = self.assert_ok(self.client.post("/api/watch/room-token/replies", json={
                "text": "100%_비밀 산책 이야기", "client_id": "reply-to-remove",
            }))
            kept = self.assert_ok(self.client.post("/api/watch/room-token/replies", json={
                "text": "밥 잘 먹었어", "client_id": "reply-to-keep",
            }))
            other = self.assert_ok(self.client.post("/api/watch/second-token/replies", json={
                "text": "다른 방 답글", "client_id": "other-room-reply",
            }))
        self.login()
        portfolio = f"/api/recipients/{rid}/portfolio?month=2026-10"
        with self.clock():
            report_id = self.assert_ok(self.client.post(portfolio))["portfolio"]["id"]
            self.assertIn("100%_비밀", str(self.assert_ok(self.client.get(portfolio))["portfolio"]))
            self.assertEqual(self.client.delete(f"/api/recipients/{rid}/replies/{other['id']}").status_code, 404)
            self.assert_ok(self.client.delete(f"/api/recipients/{rid}/replies/{gone['id']}"))
            self.assertEqual(self.client.delete(f"/api/recipients/{rid}/replies/{gone['id']}").status_code, 404)
            self.assertEqual([e["id"] for e in self.room(rid)["events"] if e["type"] == "reply"], [kept["id"]])
            after = self.assert_ok(self.client.get(portfolio))
            self.assertEqual(after["portfolio"]["id"], report_id)
            self.assertFalse(after["stale"])
            self.assertEqual(after["portfolio"]["reply_count"], 1)
            self.assertNotIn("100%_비밀", str(after["portfolio"]))
            self.assert_ok(self.client.delete(f"/api/recipients/{rid}/replies/{kept['id']}"))
            self.assertIsNone(self.assert_ok(self.client.get(portfolio))["portfolio"])
        with db.SessionLocal() as session:
            notes = session.scalars(select(Notification.text).where(Notification.kind == "senior_reply")).all()
            self.assertEqual(len(notes), 1)
            self.assertIn("다른 방 답글", notes[0])
        self.login("intruder")
        self.assertEqual(self.client.delete(f"/api/recipients/{second}/replies/{other['id']}").status_code, 404)


if __name__ == "__main__":
    unittest.main()
