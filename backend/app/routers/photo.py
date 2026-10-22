from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import serialize
from ..auth import current_user
from ..db import get_db, utcnow
from ..models import Photo, User
from ..services import face, storage

router = APIRouter(prefix="/api/photo", tags=["photo"])

MAX_UPLOAD = 15 * 1024 * 1024


@router.get("")
def get_photo(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return serialize.photo(db.scalar(select(Photo).where(Photo.user_id == user.id)))


@router.get("/image")
def get_image(user: User = Depends(current_user), db: Session = Depends(get_db)):
    photo = db.scalar(select(Photo).where(Photo.user_id == user.id))
    if not photo:
        raise HTTPException(404)
    return FileResponse(storage.abs_path(photo.path), media_type="image/jpeg")


@router.post("")
def upload_photo(file: UploadFile = File(...), user: User = Depends(current_user), db: Session = Depends(get_db)):
    if "face" not in serialize.active_consents(db, user.id):
        raise HTTPException(403, "얼굴 사진 사용 동의가 필요해요.")
    data = file.file.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "사진 파일이 너무 커요. 15MB 이하로 올려 주세요.")

    result = face.check(data)
    if not result.ok:
        return {"ok": False, "problems": result.problems, "photo": None}

    path = storage.user_dir(user.id, "photo") / "photo.jpg"
    result.image.save(path, quality=92)
    photo = db.scalar(select(Photo).where(Photo.user_id == user.id)) or Photo(user_id=user.id)
    photo.path = storage.rel_path(path)
    photo.width, photo.height = result.image.size
    photo.face = result.face
    photo.created_at = utcnow()
    db.add(photo)
    db.commit()
    return {"ok": True, "problems": [], "photo": serialize.photo(photo)}
