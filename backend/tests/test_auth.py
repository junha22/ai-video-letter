"""Authentication integration/security tests against an isolated SQLite database.

Run from the repository root: python -m unittest discover -s backend/tests -v
"""

import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import logging
import threading
from pathlib import Path
import unittest
from unittest.mock import patch

from _test_support import TEST_ROOT, app, db, settings
from fastapi.testclient import TestClient
from sqlalchemy import MetaData, func, inspect, select, update

from app import auth
from app.models import (
    AccountCredential, AuthRateLimit, AuthSession, Consent, Message,
    ParentProfile, Recipient, SeniorReply, ShareLink, User,
)


PASSWORD = "my secure password 123!"
NEW_PASSWORD = "a different password 456!"
logging.getLogger("httpx").setLevel(logging.WARNING)


class AuthenticationIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.assertEqual(settings.data_dir, TEST_ROOT)
        self.assertEqual(Path(db.engine.url.database).resolve(), (TEST_ROOT / "test.sqlite").resolve())
        db.Base.metadata.drop_all(db.engine)
        db.init_db()
        self.client = self.new_client()
        self.dev_login = patch.object(settings, "dev_login", False)
        self.dev_login.start()
        self.addCleanup(self.dev_login.stop)

    def new_client(self, ip="198.51.100.10", **kwargs):
        client = TestClient(app, client=(ip, 50000), **kwargs)
        self.addCleanup(client.close)
        return client

    def assert_ok(self, response, status=200):
        self.assertEqual(response.status_code, status, response.text)
        return response.json()

    def register(self, email="owner@example.com", *, password=PASSWORD, name="사용자", client=None, **kwargs):
        response = (client or self.client).post("/api/auth/register", json={
            "name": name, "email": email, "password": password,
        }, **kwargs)
        return self.assert_ok(response)

    def login(self, email="owner@example.com", password=PASSWORD, client=None, **kwargs):
        return (client or self.client).post("/api/auth/login", json={
            "email": email, "password": password,
        }, **kwargs)

    def cookie(self, client=None):
        value = (client or self.client).cookies.get(auth.COOKIE)
        self.assertTrue(value)
        return value

    def with_cookie(self, token):
        client = self.new_client()
        client.cookies.set(auth.COOKIE, token)
        return client

    def payload(self, token):
        body = token.split(".", 1)[0]
        return json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))

    def test_register_normalizes_email_name_and_creates_authenticated_session(self):
        data = self.register("  Owner@Example.COM  ", name="  김 민수  ")
        self.assertEqual(data["user"]["email"], "owner@example.com")
        self.assertEqual(data["user"]["name"], "김 민수")
        self.assertTrue(data["user"]["has_password"])
        me = self.assert_ok(self.client.get("/api/me"))
        self.assertEqual(me["user"]["id"], data["user"]["id"])
        self.assertEqual(me["user"]["email"], "owner@example.com")
        config = self.assert_ok(self.client.get("/api/auth/config"))
        self.assertTrue(config["password_login"])
        self.assertFalse(config["dev_login"])
        self.assertEqual(config["password_min_length"], 4)
        self.assertIsNone(config["password_max_length"])

    def test_registration_cookie_flags_and_https_secure_flag(self):
        response = self.client.post("/api/auth/register", json={
            "name": "사용자", "email": "owner@example.com", "password": PASSWORD,
        })
        self.assert_ok(response)
        cookie = response.headers["set-cookie"].lower()
        for flag in ("httponly", "samesite=lax", "path=/", "max-age="):
            self.assertIn(flag, cookie)
        with patch.object(settings, "public_base_url", "https://letters.example.com"):
            response = self.login()
            self.assert_ok(response)
            self.assertIn("secure", response.headers["set-cookie"].lower())

    def test_password_hashes_are_salted_and_secrets_never_returned(self):
        first = self.register()
        self.register("second@example.com")
        with db.SessionLocal() as session:
            credentials = session.scalars(select(AccountCredential)).all()
            self.assertEqual(len(credentials), 2)
            self.assertNotEqual(credentials[0].password_hash, credentials[1].password_hash)
            for credential in credentials:
                self.assertNotEqual(credential.password_hash, PASSWORD)
                self.assertNotIn(PASSWORD, credential.password_hash)
            sessions = session.scalars(select(AuthSession)).all()
            self.assertEqual(len(sessions), 2)
            for saved in sessions:
                self.assertNotIn(saved.token_hash, self.cookie())
        for data in (first, self.assert_ok(self.client.get("/api/me")), self.assert_ok(self.client.get("/api/auth/config"))):
            rendered = json.dumps(data)
            for secret in (PASSWORD, "password_hash", "token_hash", settings.session_secret):
                self.assertNotIn(secret, rendered)

    def test_invalid_registration_values_are_rejected_without_creating_accounts(self):
        valid = {"name": "사용자", "email": "owner@example.com", "password": PASSWORD}
        cases = (
            {"name": "   "}, {"name": "x" * 51}, {"name": 13},
            {"email": "not-an-email"}, {"email": "a@@example.com"},
            {"email": "a b@example.com"}, {"email": "a\n@example.com"},
            {"email": "홍길동@example.com"}, {"email": "a@" + "x" * 250 + ".com"},
            {"password": "x" * 3}, {"password": ""},
            {"password": 123456789012},
        )
        for changed in cases:
            with self.subTest(changed=changed):
                response = self.client.post("/api/auth/register", json={**valid, **changed})
                self.assertEqual(response.status_code, 422, response.text)
                self.assertNotIn(PASSWORD, response.text)
        with db.SessionLocal() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(User)), 0)

    def test_password_length_boundaries_unicode_and_spaces_are_preserved(self):
        for index, password in enumerate(("1234", "b" * 300, "한" * 4, "  password  ", " " * 4)):
            with self.subTest(length=len(password)):
                email = f"boundary{index}@example.com"
                self.register(email, password=password)
                self.client.cookies.clear()
                self.assert_ok(self.login(email, password))
                if password != password.strip():
                    response = self.login(email, password.strip())
                    self.assertIn(response.status_code, (401, 422), response.text)

    def test_four_character_password_works_for_register_attach_and_change(self):
        self.register(password="1234")
        self.assertEqual(self.client.post("/api/auth/password", json={
            "current_password": "1234", "new_password": "123",
        }).status_code, 422)
        self.assert_ok(self.client.post("/api/auth/password", json={
            "current_password": "1234", "new_password": "5678",
        }))
        self.assert_ok(self.login(password="5678"))
        legacy = self.new_client("198.51.100.30")
        with patch.object(settings, "dev_login", True):
            self.assert_ok(legacy.post("/api/auth/dev-login", json={"name": "short password legacy"}))
        self.assertEqual(legacy.post("/api/auth/credentials", json={
            "email": "short-legacy@example.com", "password": "123",
        }).status_code, 422)
        self.assert_ok(legacy.post("/api/auth/credentials", json={
            "email": "short-legacy@example.com", "password": "1234",
        }))
        self.assert_ok(self.login("short-legacy@example.com", "1234", client=legacy))

    def test_duplicate_email_is_case_insensitive_and_does_not_replace_credentials(self):
        original = self.register()
        response = self.client.post("/api/auth/register", json={
            "name": "hijacker", "email": " OWNER@EXAMPLE.COM ", "password": NEW_PASSWORD,
        })
        self.assertEqual(response.status_code, 409, response.text)
        self.assert_ok(self.login())
        self.assertEqual(self.assert_ok(self.client.get("/api/me"))["user"]["id"], original["user"]["id"])
        self.assertEqual(self.login(password=NEW_PASSWORD).status_code, 401)
        with db.SessionLocal() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(User)), 1)
            self.assertEqual(session.scalar(select(func.count()).select_from(AccountCredential)), 1)

    def test_concurrent_registration_of_same_email_has_one_winner_and_no_orphan_user(self):
        def register_once(index):
            with TestClient(app, client=(f"198.51.100.{index + 20}", 50000)) as client:
                return client.post("/api/auth/register", json={
                    "name": f"user{index}", "email": "race@example.com", "password": PASSWORD,
                })
        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(executor.map(register_once, range(2)))
        self.assertEqual(sorted(response.status_code for response in responses), [200, 409],
                         [response.text for response in responses])
        with db.SessionLocal() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(User)), 1)
            self.assertEqual(session.scalar(select(func.count()).select_from(AccountCredential)), 1)

    def test_login_failure_is_generic_and_does_not_authenticate_client(self):
        self.register()
        self.client.cookies.clear()
        known = self.login(password=NEW_PASSWORD)
        unknown = self.login("unknown@example.com", NEW_PASSWORD)
        self.assertEqual(known.status_code, 401, known.text)
        self.assertEqual(unknown.status_code, 401, unknown.text)
        self.assertEqual(known.json(), unknown.json())
        self.assertEqual(self.client.get("/api/me").status_code, 401)
        self.assertNotIn("owner@example.com", known.text)
        self.assertNotIn(PASSWORD, known.text)
        self.assert_ok(self.login(" OWNER@EXAMPLE.COM "))

    def test_logout_revokes_saved_cookie_and_clears_browser_session(self):
        self.register()
        token = self.cookie()
        response = self.client.post("/api/auth/logout")
        self.assert_ok(response)
        self.assertIn("max-age=0", response.headers["set-cookie"].lower())
        self.assertEqual(self.client.get("/api/me").status_code, 401)
        self.assertEqual(self.with_cookie(token).get("/api/me").status_code, 401)
        self.assert_ok(self.client.post("/api/auth/logout"))
        with db.SessionLocal() as session:
            self.assertIsNotNone(session.scalar(select(AuthSession)).revoked_at)

    def test_tampered_expired_and_unknown_session_cookies_are_rejected(self):
        self.register()
        token = self.cookie()
        payload = self.payload(token)
        tampered = token[:-1] + ("A" if token[-1] != "A" else "B")
        expired = auth.sign({**payload, "exp": 1})
        unknown = auth.sign({**payload, "sid": "a" * 64})
        legacy = auth.sign({"uid": payload["uid"], "exp": payload["exp"]})
        for value in (tampered, expired, unknown, legacy, "not-a-cookie", "x.y.z", "", "a" * 10000):
            with self.subTest(cookie=value[:35]):
                response = self.with_cookie(value).get("/api/me")
                self.assertEqual(response.status_code, 401, response.text)

    def test_signed_cookie_with_wrong_json_types_never_crashes_or_authenticates(self):
        self.register()
        payload = self.payload(self.cookie())
        cases = [None, [], [payload], 7, "text"]
        for key, values in {
            "uid": (True, "1", [1], {"id": 1}, None, 1.0, -1, 2**100),
            "exp": (True, "999999999999", None, [], {}, float("inf"), float("nan")),
            "sid": (True, 1, None, [], {}, ""),
        }.items():
            cases.extend({**payload, key: value} for value in values)
        for invalid in cases:
            with self.subTest(payload=invalid):
                response = self.with_cookie(auth.sign(invalid)).get("/api/me")
                self.assertEqual(response.status_code, 401, response.text)

    def test_server_expired_session_is_rejected_even_with_valid_signed_cookie(self):
        self.register()
        token = self.cookie()
        with db.SessionLocal() as session:
            session.execute(update(AuthSession).values(expires_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=1)))
            session.commit()
        self.assertEqual(self.with_cookie(token).get("/api/me").status_code, 401)

    def test_password_change_revokes_every_old_session_and_rotates_current_session(self):
        self.register()
        first = self.cookie()
        second_client = self.new_client("198.51.100.11")
        self.assert_ok(self.login(client=second_client))
        second = self.cookie(second_client)
        self.assertNotEqual(first, second)
        response = self.client.post("/api/auth/password", json={
            "current_password": PASSWORD, "new_password": NEW_PASSWORD,
        })
        self.assert_ok(response)
        self.assertNotIn(self.cookie(), (first, second))
        self.assert_ok(self.client.get("/api/me"))
        for old in (first, second):
            self.assertEqual(self.with_cookie(old).get("/api/me").status_code, 401)
        self.assertEqual(self.login(password=PASSWORD).status_code, 401)
        self.assert_ok(self.login(password=NEW_PASSWORD))

    def test_failed_password_change_does_not_revoke_session_or_change_password(self):
        self.register()
        token = self.cookie()
        response = self.client.post("/api/auth/password", json={
            "current_password": NEW_PASSWORD, "new_password": "another password 789!",
        })
        self.assertEqual(response.status_code, 401, response.text)
        self.assertEqual(self.cookie(), token)
        self.assert_ok(self.client.get("/api/me"))
        self.assert_ok(self.login())
        self.client.cookies.clear()
        self.assertEqual(self.client.post("/api/auth/password", json={
            "current_password": PASSWORD, "new_password": NEW_PASSWORD,
        }).status_code, 401)

    def test_login_in_flight_with_old_password_cannot_issue_session_after_change(self):
        self.register()
        verified = threading.Event()
        resume = threading.Event()
        original = auth.check_password

        # Patch the router's imported function; pause after password verification,
        # allowing a password change to commit before the old login acquires a lock.
        from app.routers import auth as routes
        response = []
        def do_login():
            with TestClient(app, client=("198.51.100.44", 50000)) as client:
                response.append(client.post("/api/auth/login", json={"email": "owner@example.com", "password": PASSWORD}))

        # FastAPI runs sync endpoints on AnyIO worker threads, so tag by the
        # distinct checked password call instead of relying on thread names.
        lock = threading.Lock()
        did_pause = False
        def pause_once(password, encoded):
            nonlocal did_pause
            result = original(password, encoded)
            with lock:
                wait = not did_pause
                did_pause = True
            if wait:
                verified.set()
                self.assertTrue(resume.wait(10))
            return result

        with patch.object(routes, "check_password", side_effect=pause_once):
            worker = threading.Thread(target=do_login)
            worker.start()
            try:
                self.assertTrue(verified.wait(10))
                self.assert_ok(self.client.post("/api/auth/password", json={"current_password": PASSWORD, "new_password": NEW_PASSWORD}))
            finally:
                resume.set()
                worker.join(10)
        self.assertFalse(worker.is_alive())
        self.assertEqual(response[0].status_code, 401, response[0].text)
        self.assert_ok(self.login(password=NEW_PASSWORD))

    def test_legacy_account_credential_attach_preserves_existing_user_and_conversations(self):
        with patch.object(settings, "dev_login", True):
            self.assert_ok(self.client.post("/api/auth/dev-login", json={"name": "legacy owner"}))
        uid = self.assert_ok(self.client.get("/api/me"))["user"]["id"]
        self.assert_ok(self.client.post("/api/consent", json={"voice": True, "face": True, "parent_receive": True}))
        self.assert_ok(self.client.put("/api/parent", json={
            "nickname": "엄마", "relation": "어머니", "phone": "01012345678", "child_call_name": "민수",
        }))
        rid = self.assert_ok(self.client.get("/api/recipients"))[0]["id"]
        with db.SessionLocal() as session:
            parent = session.scalar(select(ParentProfile).where(ParentProfile.user_id == uid))
            message = Message(user_id=uid, parent_id=parent.id, recipient_id=rid,
                              memo="preserve memo", template="greeting", script="엄마 안녕하세요", status="approved")
            session.add(message)
            session.flush()
            mid, parent_id = message.id, parent.id
            session.add(ShareLink(message_id=mid, token="legacy-preserved-link", expires_at=datetime(2099, 1, 1)))
            session.add(SeniorReply(user_id=uid, recipient_id=rid, text="잘 봤어", client_id="legacy-reply"))
            session.commit()
        old_cookie = self.cookie()
        self.assert_ok(self.client.post("/api/auth/credentials", json={"email": "legacy@example.com", "password": PASSWORD}))
        self.assertEqual(self.assert_ok(self.client.get("/api/me"))["user"]["id"], uid)
        self.assertEqual(self.with_cookie(old_cookie).get("/api/me").status_code, 401)
        with patch.object(settings, "dev_login", True):
            response = self.new_client().post("/api/auth/dev-login", json={"name": "legacy owner"})
            self.assertIn(response.status_code, (401, 403, 409), response.text)
        self.client.cookies.clear()
        self.assert_ok(self.login("legacy@example.com"))
        self.assertEqual(self.assert_ok(self.client.get("/api/me"))["user"]["id"], uid)
        with db.SessionLocal() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(User)), 1)
            self.assertEqual(session.get(ParentProfile, parent_id).user_id, uid)
            self.assertEqual(session.get(Message, mid).memo, "preserve memo")
            self.assertEqual(session.get(Recipient, rid).user_id, uid)
            self.assertEqual(session.scalar(select(ShareLink)).token, "legacy-preserved-link")
            self.assertEqual(session.scalar(select(SeniorReply)).text, "잘 봤어")
            self.assertEqual(session.scalar(select(func.count()).select_from(Consent)), 3)

    def test_credentials_require_existing_legacy_login_and_cannot_replace_an_account(self):
        body = {"email": "owner@example.com", "password": PASSWORD}
        self.assertEqual(self.client.post("/api/auth/credentials", json=body).status_code, 401)
        self.register()
        response = self.client.post("/api/auth/credentials", json={"email": "changed@example.com", "password": NEW_PASSWORD})
        self.assertEqual(response.status_code, 409, response.text)
        self.assert_ok(self.login())
        self.assertEqual(self.login("changed@example.com", NEW_PASSWORD).status_code, 401)

    def test_dev_login_is_disabled_by_default_and_rejects_whitespace_names(self):
        response = self.client.post("/api/auth/dev-login", json={"name": "owner"})
        self.assertEqual(response.status_code, 404, response.text)
        with patch.object(settings, "dev_login", True):
            response = self.client.post("/api/auth/dev-login", json={"name": "    "})
            self.assertEqual(response.status_code, 422, response.text)
        with db.SessionLocal() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(User)), 0)

    def test_cross_origin_authentication_requests_are_blocked_before_mutation(self):
        payload = {"name": "사용자", "email": "owner@example.com", "password": PASSWORD}
        for origin in ("https://evil.example", "null", "http://testserver.evil.example"):
            with self.subTest(origin=origin):
                response = self.client.post("/api/auth/register", json=payload, headers={"Origin": origin})
                self.assertEqual(response.status_code, 403, response.text)
        with db.SessionLocal() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(User)), 0)
        self.assert_ok(self.client.post("/api/auth/register", json=payload, headers={"Origin": "http://testserver"}))
        token = self.cookie()
        requests = (
            ("post", "/api/auth/login", {"email": payload["email"], "password": PASSWORD}),
            ("post", "/api/auth/logout", {}),
            ("post", "/api/auth/credentials", {"email": "evil@example.com", "password": NEW_PASSWORD}),
            ("post", "/api/auth/password", {"current_password": PASSWORD, "new_password": NEW_PASSWORD}),
            ("put", "/api/parent", {"nickname": "엄마", "relation": "어머니", "phone": "01012345678"}),
        )
        for method, path, body in requests:
            with self.subTest(path=path):
                response = getattr(self.client, method)(path, json=body, headers={"Origin": "https://evil.example"})
                self.assertEqual(response.status_code, 403, response.text)
                self.assertEqual(self.cookie(), token)
        self.assert_ok(self.client.get("/api/me"))
        self.assert_ok(self.login())
        self.assertIsNone(self.assert_ok(self.client.get("/api/parent")))

    def test_fetch_metadata_blocks_cross_site_requests_without_origin(self):
        response = self.client.post("/api/auth/register", json={
            "name": "사용자", "email": "owner@example.com", "password": PASSWORD,
        }, headers={"Sec-Fetch-Site": "cross-site"})
        self.assertEqual(response.status_code, 403, response.text)

    def test_login_rate_limit_follows_normalized_credential_across_client_ips(self):
        self.register()
        for index in range(10):
            client = self.new_client(f"203.0.113.{index + 1}")
            response = self.login(" OWNER@EXAMPLE.COM ", NEW_PASSWORD, client=client)
            self.assertEqual(response.status_code, 401, response.text)
        limited = self.login(password=NEW_PASSWORD, client=self.new_client("203.0.113.99"))
        self.assertEqual(limited.status_code, 429, limited.text)
        self.assertIn("retry-after", limited.headers)
        self.register("unrelated@example.com", client=self.new_client("203.0.113.100"))
        self.assert_ok(self.login("unrelated@example.com", client=self.new_client("203.0.113.101")))
        with db.SessionLocal() as session:
            rows = session.scalars(select(AuthRateLimit)).all()
            self.assertTrue(rows, "Rate limiting must survive application workers/restarts")
            self.assertTrue(all("owner@example.com" not in row.key for row in rows))

    def test_login_client_limit_does_not_trust_rotating_x_forwarded_for(self):
        for index in range(30):
            response = self.login(f"missing{index}@example.com", NEW_PASSWORD,
                                  headers={"X-Forwarded-For": f"203.0.113.{index + 1}"})
            self.assertEqual(response.status_code, 401, response.text)
        response = self.login("missing-last@example.com", NEW_PASSWORD,
                              headers={"X-Forwarded-For": "203.0.113.200"})
        self.assertEqual(response.status_code, 429, response.text)
        other = self.new_client("198.51.100.200")
        self.assertEqual(self.login("fresh@example.com", NEW_PASSWORD, client=other).status_code, 401)

    def test_registration_rate_limit_uses_client_scope_and_expires(self):
        for index in range(10):
            self.register(f"signup{index}@example.com")
        response = self.client.post("/api/auth/register", json={
            "name": "overflow", "email": "overflow@example.com", "password": PASSWORD,
        })
        self.assertEqual(response.status_code, 429, response.text)
        with db.SessionLocal() as session:
            session.execute(update(AuthRateLimit).values(expires_at=datetime(2000, 1, 1)))
            session.commit()
        self.register("after-window@example.com")

    def test_legacy_sqlite_user_schema_gains_auth_tables_without_losing_rows(self):
        db.Base.metadata.drop_all(db.engine)
        legacy = MetaData()
        for name in ("users", "parent_profiles"):
            db.Base.metadata.tables[name].to_metadata(legacy)
        legacy.create_all(db.engine)
        with db.engine.begin() as connection:
            connection.execute(legacy.tables["users"].insert().values(id=41, name="legacy owner", kakao_id="dev:legacy owner"))
            connection.execute(legacy.tables["parent_profiles"].insert().values(
                id=51, user_id=41, nickname="엄마", relation="어머니", phone="010-1234-5678",
            ))
        db.init_db()
        db.init_db()
        tables = set(inspect(db.engine).get_table_names())
        self.assertTrue({AccountCredential.__tablename__, AuthSession.__tablename__, AuthRateLimit.__tablename__} <= tables)
        with db.SessionLocal() as session:
            self.assertEqual(session.get(User, 41).name, "legacy owner")
            self.assertEqual(session.get(ParentProfile, 51).phone, "010-1234-5678")
            self.assertEqual(session.scalar(select(func.count()).select_from(AccountCredential)), 0)


if __name__ == "__main__":
    unittest.main()
