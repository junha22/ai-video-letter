"""Private, account-owned album cover upload, retrieval, and reset."""

import secrets

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import serialize
from ..auth import current_user
from ..db import get_db, iso, utcnow
from ..models import AlbumCover, User
from ..services import conversations, private_images, storage

router = APIRouter(prefix="/api/album-cover", tags=["album-cover"])
MAX_UPLOAD = private_images.MAX_UPLOAD
MAX_PIXELS = private_images.MAX_PIXELS
MIME_TYPES = private_images.MIME_TYPES
PRIVATE = private_images.PRIVATE


def _owned(db: Session, user_id: int) -> AlbumCover | None:
    return db.scalar(select(AlbumCover).where(AlbumCover.user_id == user_id))


def _info(cover: AlbumCover | None) -> dict | None:
    if not cover:
        return None
    return {"url": f"/api/album-cover/image?v={cover.version}", "width": cover.width,
            "height": cover.height, "updated_at": iso(cover.updated_at)}


def _normalize(data: bytes) -> tuple[bytes, int, int]:
    return private_images.normalize(data, max_pixels=MAX_PIXELS)


@router.get("")
def get_cover(response: Response, user: User = Depends(current_user), db: Session = Depends(get_db)):
    response.headers.update(PRIVATE)
    return _info(_owned(db, user.id))


@router.get("/image")
def cover_image(v: str | None = None, user: User = Depends(current_user), db: Session = Depends(get_db)):
    cover = _owned(db, user.id)
    if not cover or (v is not None and v != cover.version):
        raise HTTPException(404, "표지 이미지를 찾을 수 없어요.")
    try:
        data = storage.abs_path(cover.path).read_bytes()
    except FileNotFoundError:
        raise HTTPException(404, "표지 이미지를 찾을 수 없어요.") from None
    return Response(content=data, media_type="image/jpeg", headers=PRIVATE)


@router.post("")
def upload_cover(file: UploadFile = File(...), user: User = Depends(current_user), db: Session = Depends(get_db)):
    if file.content_type not in MIME_TYPES:
        raise HTTPException(415, "JPG, PNG, WebP 이미지를 선택해 주세요.")
    data = file.file.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "표지 이미지는 15MB 이하로 선택해 주세요.")
    normalized, width, height = _normalize(data)
    conversations.lock_owner(db, user.id)
    if not serialize.consent_ok(db, user.id):
        raise HTTPException(403, "먼저 서비스 사용 동의를 완료해 주세요.")
    cover = _owned(db, user.id)
    previous = cover.path if cover else None
    version = secrets.token_hex(16)
    path = storage.user_dir(user.id, "album-cover") / f"cover-{version}.jpg"
    path.write_bytes(normalized)
    try:
        cover = cover or AlbumCover(user_id=user.id)
        cover.path, cover.version = storage.rel_path(path), version
        cover.width, cover.height, cover.updated_at = width, height, utcnow()
        db.add(cover)
        db.commit()
    except Exception:
        db.rollback()
        path.unlink(missing_ok=True)
        raise
    storage.delete_file(previous)
    return _info(cover)


@router.delete("")
def reset_cover(user: User = Depends(current_user), db: Session = Depends(get_db)):
    conversations.lock_owner(db, user.id)
    cover = _owned(db, user.id)
    previous = cover.path if cover else None
    if cover:
        db.delete(cover)
    db.commit()
    storage.delete_file(previous)
    return {"ok": True}
