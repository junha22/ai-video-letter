"""Private cover persistence, image handling, replacement, and consent lifecycle."""

from io import BytesIO
import logging
import unittest
from unittest.mock import patch

from PIL import Image
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from _test_support import TEST_ROOT, app, db, settings, using_isolated_database
from app.models import AlbumCover, Photo, User
from app.routers import album_cover
from app.services import storage

logging.getLogger("httpx").setLevel(logging.WARNING)


def picture(size=(120, 80), color=(180, 110, 90, 128), fmt="PNG", exif=None):
    image = Image.new("RGBA" if len(color) == 4 else "RGB", size, color)
    output = BytesIO()
    image.save(output, format=fmt, **({"exif": exif} if exif is not None else {}))
    return output.getvalue()


class AlbumCoverTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(using_isolated_database())
        self.assertEqual(settings.data_dir, TEST_ROOT)
        storage.delete_tree(TEST_ROOT / "users")
        db.Base.metadata.drop_all(db.engine)
        db.init_db()
        self.flag = patch.object(settings, "dev_login", True)
        self.flag.start()
        self.addCleanup(self.flag.stop)
        self.client = self.owner("cover-owner")
        self.uid = self.client.get("/api/me").json()["user"]["id"]

    def owner(self, name):
        client = TestClient(app)
        self.addCleanup(client.close)
        self.assertEqual(client.post("/api/auth/dev-login", json={"name": name}).status_code, 200)
        self.assertEqual(client.post("/api/consent", json={"voice": True, "face": True, "parent_receive": True}).status_code, 200)
        return client

    def upload(self, data=None, mime="image/png", client=None, filename="family.png"):
        return (client or self.client).post("/api/album-cover", files={"file": (filename, data if data is not None else picture(), mime)})

    def row(self):
        with db.SessionLocal() as session:
            return session.scalar(select(AlbumCover).where(AlbumCover.user_id == self.uid))

    def test_auth_required_for_metadata_upload_image_and_reset(self):
        with TestClient(app) as anonymous:
            for method, url in (("GET", "/api/album-cover"), ("GET", "/api/album-cover/image"), ("DELETE", "/api/album-cover")):
                self.assertEqual(anonymous.request(method, url).status_code, 401)
            self.assertEqual(self.upload(client=anonymous).status_code, 401)

    def test_upload_persists_across_sessions_and_serves_private_normalized_image(self):
        self.assertIsNone(self.client.get("/api/album-cover").json())
        response = self.upload(filename="../../untrusted.png")
        self.assertEqual(response.status_code, 200, response.text)
        cover = response.json()
        self.assertEqual((cover["width"], cover["height"]), (120, 80))
        self.assertIn("private", self.client.get("/api/album-cover").headers["cache-control"])
        with TestClient(app, cookies=self.client.cookies) as another_session:
            self.assertEqual(another_session.get("/api/album-cover").json(), cover)
            image = another_session.get(cover["url"])
        self.assertEqual(image.status_code, 200)
        self.assertEqual(image.headers["content-type"], "image/jpeg")
        self.assertEqual(image.headers["cache-control"], "private, no-store")
        self.assertEqual(image.headers["x-content-type-options"], "nosniff")
        with Image.open(BytesIO(image.content)) as decoded:
            self.assertEqual(decoded.mode, "RGB")
            self.assertEqual(decoded.size, (120, 80))
        self.assertTrue(storage.abs_path(self.row().path).is_relative_to(TEST_ROOT / "users" / str(self.uid)))

    def test_replace_removes_previous_file_and_old_version(self):
        first = self.upload().json()
        old = storage.abs_path(self.row().path)
        second = self.upload(picture(color=(20, 50, 80, 255))).json()
        self.assertNotEqual(first["url"], second["url"])
        self.assertFalse(old.exists())
        self.assertEqual(self.client.get(first["url"]).status_code, 404)
        self.assertEqual(self.client.get(second["url"]).status_code, 200)
        self.assertEqual(len(list(storage.user_dir(self.uid, "album-cover").glob("*.jpg"))), 1)

    def test_reset_restores_default_and_is_idempotent(self):
        cover = self.upload().json()
        path = storage.abs_path(self.row().path)
        self.assertEqual(self.client.delete("/api/album-cover").status_code, 200)
        self.assertIsNone(self.client.get("/api/album-cover").json())
        self.assertIsNone(self.row())
        self.assertFalse(path.exists())
        self.assertEqual(self.client.get(cover["url"]).status_code, 404)
        self.assertEqual(self.client.delete("/api/album-cover").status_code, 200)

    def test_accounts_cannot_read_or_reset_each_others_cover(self):
        first = self.upload().json()
        other = self.owner("another-cover-owner")
        self.assertIsNone(other.get("/api/album-cover").json())
        self.assertEqual(other.get(first["url"]).status_code, 404)
        other_cover = self.upload(client=other).json()
        self.assertEqual(other.get(first["url"]).status_code, 404)
        self.assertEqual(self.client.get(other_cover["url"]).status_code, 404)
        other.delete("/api/album-cover")
        self.assertEqual(self.client.get(first["url"]).status_code, 200)

    def test_bad_or_unsupported_upload_keeps_last_good_cover(self):
        good = self.upload().json()
        for data, mime, status in ((b"not an image", "image/png", 422), (b"<svg></svg>", "image/svg+xml", 415),
                                   (picture(fmt="GIF"), "image/png", 415), (b"", "image/png", 422)):
            with self.subTest(mime=mime, status=status):
                response = self.upload(data, mime)
                self.assertEqual(response.status_code, status, response.text)
                self.assertEqual(self.client.get("/api/album-cover").json(), good)

    def test_size_and_resolution_limits_keep_existing_cover(self):
        good = self.upload().json()
        with patch.object(album_cover, "MAX_UPLOAD", 16):
            self.assertEqual(self.upload(b"x" * 17).status_code, 413)
        with patch.object(album_cover, "MAX_PIXELS", 100):
            self.assertEqual(self.upload(picture((11, 10))).status_code, 422)
        self.assertEqual(self.client.get("/api/album-cover").json(), good)

    def test_exif_orientation_metadata_stripping_and_resize(self):
        exif = Image.Exif()
        exif[274] = 6
        exif[315] = "private author"
        cover = self.upload(picture((3000, 1500), (80, 90, 100), "JPEG", exif), "image/jpeg").json()
        self.assertEqual((cover["width"], cover["height"]), (1024, 2048))
        with Image.open(BytesIO(self.client.get(cover["url"]).content)) as result:
            self.assertFalse(result.getexif())

    def test_commit_failure_keeps_previous_cover_without_orphan_file(self):
        good = self.upload().json()
        with patch.object(Session, "commit", side_effect=RuntimeError("test database failure")):
            with self.assertRaises(RuntimeError):
                self.upload(picture(color=(50, 60, 70, 255)))
        self.assertEqual(self.client.get("/api/album-cover").json(), good)
        self.assertEqual(len(list(storage.user_dir(self.uid, "album-cover").glob("*.jpg"))), 1)

    def test_cover_does_not_replace_video_face_and_withdrawal_removes_both(self):
        face_path = storage.user_dir(self.uid, "photo") / "photo.jpg"
        face_path.write_bytes(picture(fmt="JPEG", color=(90, 90, 90)))
        with db.SessionLocal() as session:
            session.add(Photo(user_id=self.uid, path=storage.rel_path(face_path), width=120, height=80, face=[0, 0, 60, 60]))
            session.commit()
        photo = self.client.get("/api/photo").json()
        cover = self.upload().json()
        cover_path = storage.abs_path(self.row().path)
        self.assertEqual(self.client.get("/api/photo").json(), photo)
        response = self.client.post("/api/consent/withdraw")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["deleted"]["album_cover_files"], 1)
        self.assertFalse(cover_path.exists())
        self.assertFalse(face_path.exists())
        self.assertIsNone(self.row())
        self.assertEqual(self.client.get(cover["url"]).status_code, 404)
        self.assertEqual(self.upload().status_code, 403)

    def test_existing_database_gets_new_cover_table_without_losing_users(self):
        AlbumCover.__table__.drop(db.engine)
        db.init_db()
        with db.SessionLocal() as session:
            self.assertIsNotNone(session.get(User, self.uid))
        self.assertIsNone(self.client.get("/api/album-cover").json())
        self.assertEqual(self.upload().status_code, 200)
