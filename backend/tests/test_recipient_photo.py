"""Recipient image ownership, persistence, public privacy, and cleanup."""
from datetime import timedelta
import json
import logging
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from _test_support import TEST_ROOT, app, db, settings, using_isolated_database
from test_album_cover import picture
from app.db import utcnow
from app.models import AlbumCover, Message, ParentProfile, Recipient, RecipientPhoto, ShareLink, User
from app.services import private_images, storage

logging.getLogger("httpx").setLevel(logging.WARNING)


class RecipientPhotoTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(using_isolated_database())
        self.assertEqual(settings.data_dir, TEST_ROOT)
        storage.delete_tree(TEST_ROOT / "users")
        db.Base.metadata.drop_all(db.engine)
        db.init_db()
        self.flag = patch.object(settings, "dev_login", True)
        self.flag.start()
        self.addCleanup(self.flag.stop)
        self.client, self.uid, self.mom = self.owner("photo-owner")
        response = self.client.post("/api/recipients", json={"nickname": "아빠", "relation": "아버지"})
        self.assertEqual(response.status_code, 201, response.text)
        self.dad = response.json()["id"]

    def owner(self, name):
        client = TestClient(app)
        self.addCleanup(client.close)
        self.assertEqual(client.post("/api/auth/dev-login", json={"name": name}).status_code, 200)
        uid = client.get("/api/me").json()["user"]["id"]
        self.assertEqual(client.post("/api/consent", json={"voice": True, "face": True, "parent_receive": True}).status_code, 200)
        response = client.post("/api/recipients", json={"nickname": "엄마", "relation": "어머니"})
        self.assertEqual(response.status_code, 201, response.text)
        return client, uid, response.json()["id"]

    def upload(self, rid=None, data=None, mime="image/png", client=None):
        return (client or self.client).post(f"/api/recipients/{rid or self.mom}/photo", files={"file": ("family.png", data if data is not None else picture(), mime)})

    def metadata(self, rid=None):
        return self.client.get(f"/api/recipients/{rid or self.mom}/photo").json()

    def row(self, rid=None):
        with db.SessionLocal() as session:
            return session.scalar(select(RecipientPhoto).where(RecipientPhoto.recipient_id == (rid or self.mom)))

    def test_auth_required_for_all_photo_routes(self):
        with TestClient(app) as anonymous:
            for method, suffix in (("GET", ""), ("GET", "/image"), ("DELETE", "")):
                self.assertEqual(anonymous.request(method, f"/api/recipients/{self.mom}/photo{suffix}").status_code, 401)
            self.assertEqual(self.upload(client=anonymous).status_code, 401)

    def test_family_photos_are_separate_persistent_and_in_recipient_responses(self):
        self.assertIsNone(self.metadata())
        mom = self.upload().json()
        dad = self.upload(self.dad, picture(color=(30, 60, 90, 255))).json()
        self.assertNotEqual(mom["url"], dad["url"])
        with TestClient(app, cookies=self.client.cookies) as second:
            rows = {r["id"]: r for r in second.get("/api/recipients").json()}
            self.assertEqual(rows[self.mom]["photo"], mom)
            self.assertEqual(rows[self.dad]["photo"], dad)
            self.assertEqual(second.get(f"/api/recipients/{self.mom}").json()["photo"], mom)
            image = second.get(mom["url"])
            self.assertEqual(image.status_code, 200)
            self.assertEqual(image.headers["content-type"], "image/jpeg")
            self.assertEqual(image.headers["cache-control"], "private, no-store")
        response = self.client.put(f"/api/recipients/{self.mom}", json={"nickname": "어머니", "relation": "어머니"})
        self.assertEqual(response.json()["photo"], mom)

    def test_other_accounts_and_missing_recipients_cannot_read_change_or_delete(self):
        mom = self.upload().json()
        other, _, other_rid = self.owner("other-photo-owner")
        for method, suffix in (("GET", ""), ("GET", "/image"), ("DELETE", "")):
            self.assertEqual(other.request(method, f"/api/recipients/{self.mom}/photo{suffix}").status_code, 404)
        self.assertEqual(self.upload(client=other).status_code, 404)
        self.assertEqual(other.get(mom["url"]).status_code, 404)
        self.assertEqual(self.client.get(f"/api/recipients/{other_rid}/photo").status_code, 404)
        self.assertEqual(self.upload(999999).status_code, 404)
        self.assertEqual(self.metadata(), mom)

    def test_replace_invalidates_old_image_and_reset_only_changes_selected_family(self):
        first = self.upload().json()
        old = storage.abs_path(self.row().path)
        dad = self.upload(self.dad).json()
        cover = self.client.post("/api/album-cover", files={"file": ("cover.png", picture(), "image/png")}).json()
        second = self.upload(data=picture(color=(10, 20, 30, 255))).json()
        self.assertNotEqual(first["url"], second["url"])
        self.assertFalse(old.exists())
        self.assertEqual(self.client.get(first["url"]).status_code, 404)
        self.assertEqual(self.client.delete(f"/api/recipients/{self.mom}/photo").status_code, 200)
        self.assertIsNone(self.metadata())
        self.assertEqual(self.client.get(second["url"]).status_code, 404)
        self.assertEqual(self.metadata(self.dad), dad)
        self.assertEqual(self.client.get("/api/album-cover").json(), cover)
        self.assertEqual(self.client.delete(f"/api/recipients/{self.mom}/photo").status_code, 200)

    def test_invalid_files_and_upload_limits_preserve_previous_photo(self):
        good = self.upload().json()
        for data, mime, status in ((b"bad", "image/png", 422), (b"<svg/>", "image/svg+xml", 415), (picture(fmt="GIF"), "image/png", 415)):
            with self.subTest(mime=mime):
                self.assertEqual(self.upload(data=data, mime=mime).status_code, status)
                self.assertEqual(self.metadata(), good)
        with patch.object(private_images, "MAX_UPLOAD", 16):
            self.assertEqual(self.upload(data=b"x"*17).status_code, 413)
        self.assertEqual(self.metadata(), good)

    def test_db_failure_preserves_saved_photo_and_cleans_new_file(self):
        good = self.upload().json()
        with patch.object(Session, "commit", side_effect=RuntimeError("test database failure")):
            with self.assertRaises(RuntimeError):
                self.upload(data=picture(color=(90, 20, 50, 255)))
        self.assertEqual(self.metadata(), good)
        self.assertEqual(len(list(storage.user_dir(self.uid, "recipient-photos", str(self.mom)).glob("*.jpg"))), 1)

    def test_private_photo_never_appears_in_shared_room_or_public_recipient(self):
        photo = self.upload().json()
        with db.SessionLocal() as session:
            parent = session.scalar(select(ParentProfile).where(ParentProfile.user_id == self.uid))
            message = Message(user_id=self.uid, parent_id=parent.id, recipient_id=self.mom,
                              memo="private", template="greeting", script="안부 전해요", status="approved", approved_at=utcnow())
            session.add(message)
            session.flush()
            session.add(ShareLink(message_id=message.id, token="recipient-photo-private-test", expires_at=utcnow()+timedelta(days=1)))
            session.commit()
        with TestClient(app) as anonymous:
            for suffix in ("", "/feed"):
                response = anonymous.get("/api/watch/recipient-photo-private-test"+suffix)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertNotIn(photo["url"], response.text)
                self.assertNotIn('"photo"', json.dumps(response.json().get("recipient", {})))
            self.assertEqual(anonymous.get(photo["url"]).status_code, 401)

    def test_withdrawal_cleans_all_owner_photos_but_preserves_other_account(self):
        mom = self.upload().json()
        dad = self.upload(self.dad).json()
        other, _, other_rid = self.owner("withdraw-other")
        other_photo = self.upload(other_rid, client=other).json()
        response = self.client.post("/api/consent/withdraw")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["deleted"]["recipient_photo_files"], 2)
        self.assertIsNone(self.metadata())
        self.assertIsNone(self.metadata(self.dad))
        self.assertEqual(self.client.get(mom["url"]).status_code, 404)
        self.assertEqual(self.client.get(dad["url"]).status_code, 404)
        self.assertEqual(other.get(other_photo["url"]).status_code, 200)
        self.assertEqual(self.upload().status_code, 403)

    def test_existing_database_creates_new_table_without_losing_users_or_recipients(self):
        RecipientPhoto.__table__.drop(db.engine)
        db.init_db()
        with db.SessionLocal() as session:
            self.assertIsNotNone(session.get(User, self.uid))
            self.assertIsNotNone(session.get(Recipient, self.mom))
        self.assertIsNone(self.metadata())
        self.assertEqual(self.upload().status_code, 200)
