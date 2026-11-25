import random

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import serialize
from ..auth import current_user
from ..config import settings
from ..db import get_db, iso, utcnow
from ..models import Photo, User
from ..services import face, jobs, storage

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
    # 어린 시절 사진은 예전 사진으로 만든 것이라 지운다. 새 사진으로 다시 만든다
    storage.delete_file(photo.young_path)
    photo.young_path = photo.young_face = None
    db.add(photo)
    db.commit()
    return {"ok": True, "problems": [], "photo": serialize.photo(photo)}


# 어린 시절 사진 (docs/YOUNG_MODE.md): 영상 전에 한 장 만들어 보여 주고, 마음에 들지 않으면 다시 만든다


@router.get("/young")
def young_state(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return serialize.young_photo(db, user.id, db.scalar(select(Photo).where(Photo.user_id == user.id)))


@router.post("/young")
def make_young(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """만들기·다시 만들기. 약 30초(T4)라 워커가 만들고 화면은 GET으로 기다린다."""
    if "face" not in serialize.active_consents(db, user.id):
        raise HTTPException(403, "얼굴 사진 사용 동의가 필요해요.")
    photo = db.scalar(select(Photo).where(Photo.user_id == user.id))
    if not photo:
        raise HTTPException(400, "얼굴 사진을 먼저 올려 주세요.")
    if not settings.comfyui_url:
        raise HTTPException(409, "이 서버에서는 어린 시절 사진을 만들 수 없어요. 원본 사진을 그대로 써요.")
    state = serialize.young_photo(db, user.id, photo)
    if state["making"]:
        return state
    # 다시 만들 때마다 새 seed라서 다른 사진이 나온다
    seed = random.randrange(1, 2**31)
    jobs.enqueue(db, "young_photo", user.id, payload={"seed": seed, "photo_at": iso(photo.created_at)}, max_attempts=2)
    db.commit()
    return serialize.young_photo(db, user.id, photo)


@router.get("/young/image")
def young_image(user: User = Depends(current_user), db: Session = Depends(get_db)):
    photo = db.scalar(select(Photo).where(Photo.user_id == user.id))
    if not photo or not photo.young_path or not storage.abs_path(photo.young_path).exists():
        raise HTTPException(404)
    return FileResponse(storage.abs_path(photo.young_path), media_type="image/png")
