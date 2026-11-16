"""Private, account-owned album cover upload, retrieval, and reset."""

from io import BytesIO
import secrets
import warnings

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import serialize
from ..auth import current_user
from ..db import get_db, iso, utcnow
from ..models import AlbumCover, User
from ..services import conversations, storage

router = APIRouter(prefix="/api/album-cover", tags=["album-cover"])
MAX_UPLOAD = 15 * 1024 * 1024
MAX_PIXELS = 40_000_000
MAX_SIDE = 2048
FORMATS = {"JPEG", "PNG", "WEBP"}
MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}
PRIVATE = {"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"}


def _owned(db: Session, user_id: int) -> AlbumCover | None:
    return db.scalar(select(AlbumCover).where(AlbumCover.user_id == user_id))


def _info(cover: AlbumCover | None) -> dict | None:
    if not cover:
        return None
    return {"url": f"/api/album-cover/image?v={cover.version}", "width": cover.width,
            "height": cover.height, "updated_at": iso(cover.updated_at)}


def _normalize(data: bytes) -> tuple[bytes, int, int]:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as source:
                if source.format not in FORMATS or getattr(source, "is_animated", False):
                    raise HTTPException(415, "움직이지 않는 JPG, PNG, WebP 이미지를 선택해 주세요.")
                if source.width * source.height > MAX_PIXELS:
                    raise HTTPException(422, "이미지 해상도가 너무 커요. 4천만 화소 이하로 줄여 주세요.")
                image = ImageOps.exif_transpose(source)
                image.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)
                if image.mode in ("RGBA", "LA") or "transparency" in image.info:
                    rgba = image.convert("RGBA")
                    rgb = Image.new("RGB", image.size, (255, 250, 244))
                    rgb.paste(rgba, mask=rgba.getchannel("A"))
                    image = rgb
                else:
                    image = image.convert("RGB")
                output = BytesIO()
                # Re-encode without EXIF/location metadata or the original filename.
                image.save(output, format="JPEG", quality=90, optimize=True)
                return output.getvalue(), image.width, image.height
    except HTTPException:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombWarning, Image.DecompressionBombError):
        raise HTTPException(422, "이미지를 읽지 못했어요. 정상적인 JPG, PNG, WebP 파일을 선택해 주세요.") from None


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
