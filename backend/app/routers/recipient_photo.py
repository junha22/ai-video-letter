"""Authenticated per-recipient display photo; never exposed in shared rooms."""
import secrets

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import serialize
from ..auth import current_user
from ..db import get_db, utcnow
from ..models import RecipientPhoto, User
from ..services import conversations, private_images, storage

router = APIRouter(prefix="/api/recipients/{recipient_id}/photo", tags=["recipient-photo"])


def _owned(db: Session, user: User, recipient_id: int) -> RecipientPhoto | None:
    conversations.owned_recipient(db, user, recipient_id)
    return db.scalar(select(RecipientPhoto).where(RecipientPhoto.recipient_id == recipient_id, RecipientPhoto.user_id == user.id))


def _info(photo: RecipientPhoto | None, recipient_id: int):
    return private_images.image_info(photo, f"/api/recipients/{recipient_id}/photo/image")


@router.get("")
def get_photo(recipient_id: int, response: Response, user: User = Depends(current_user), db: Session = Depends(get_db)):
    response.headers.update(private_images.PRIVATE)
    return _info(_owned(db, user, recipient_id), recipient_id)


@router.get("/image")
def image(recipient_id: int, v: str | None = None, user: User = Depends(current_user), db: Session = Depends(get_db)):
    photo = _owned(db, user, recipient_id)
    if not photo or (v is not None and v != photo.version):
        raise HTTPException(404, "수신자 사진을 찾을 수 없어요.")
    try:
        data = storage.abs_path(photo.path).read_bytes()
    except FileNotFoundError:
        raise HTTPException(404, "수신자 사진을 찾을 수 없어요.") from None
    return Response(content=data, media_type="image/jpeg", headers=private_images.PRIVATE)


@router.post("")
def upload(recipient_id: int, file: UploadFile = File(...), user: User = Depends(current_user), db: Session = Depends(get_db)):
    conversations.owned_recipient(db, user, recipient_id)
    if file.content_type not in private_images.MIME_TYPES:
        raise HTTPException(415, "JPG, PNG, WebP 이미지를 선택해 주세요.")
    data = file.file.read(private_images.MAX_UPLOAD + 1)
    if len(data) > private_images.MAX_UPLOAD:
        raise HTTPException(413, "수신자 사진은 15MB 이하로 선택해 주세요.")
    normalized, width, height = private_images.normalize(data)
    conversations.lock_owner(db, user.id)
    if not serialize.consent_ok(db, user.id):
        raise HTTPException(403, "먼저 서비스 사용 동의를 완료해 주세요.")
    photo = _owned(db, user, recipient_id)
    previous = photo.path if photo else None
    version = secrets.token_hex(16)
    path = storage.user_dir(user.id, "recipient-photos", str(recipient_id)) / f"photo-{version}.jpg"
    path.write_bytes(normalized)
    try:
        photo = photo or RecipientPhoto(user_id=user.id, recipient_id=recipient_id)
        photo.path, photo.version = storage.rel_path(path), version
        photo.width, photo.height, photo.updated_at = width, height, utcnow()
        db.add(photo)
        db.commit()
    except Exception:
        db.rollback()
        path.unlink(missing_ok=True)
        raise
    storage.delete_file(previous)
    return _info(photo, recipient_id)


@router.delete("")
def reset(recipient_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    conversations.lock_owner(db, user.id)
    photo = _owned(db, user, recipient_id)
    previous = photo.path if photo else None
    if photo:
        db.delete(photo)
    db.commit()
    storage.delete_file(previous)
    return {"ok": True}
