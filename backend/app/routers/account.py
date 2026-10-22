import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from .. import serialize
from ..auth import current_user
from ..db import get_db, utcnow
from ..models import Consent, DeletionLog, Job, Message, ParentProfile, Photo, ShareLink, User, VoiceProfile, VoiceSample
from ..services import storage

router = APIRouter(prefix="/api", tags=["account"])


@router.get("/me")
def get_me(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return serialize.me(db, user)


@router.get("/consent")
def get_consent(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return serialize.consent_state(db, user.id)


class ConsentIn(BaseModel):
    voice: bool
    face: bool
    parent_receive: bool


@router.post("/consent")
def give_consent(body: ConsentIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not (body.voice and body.face and body.parent_receive):
        raise HTTPException(400, "서비스를 쓰려면 세 항목 모두 동의가 필요해요.")
    active = serialize.active_consents(db, user.id)
    for item in serialize.CONSENT_ITEMS:
        if item["kind"] not in active:
            db.add(Consent(user_id=user.id, kind=item["kind"], version=serialize.CONSENT_VERSION))
    db.commit()
    return serialize.consent_state(db, user.id)


@router.post("/consent/withdraw")
def withdraw_consent(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """동의 철회: 녹음, 목소리 모델, 사진, 영상 파일을 모두 지우고 기록을 남긴다."""
    root = storage.user_dir(user.id)
    detail = {
        "voice_files": storage.delete_tree(root / "voice"),
        "photo_files": storage.delete_tree(root / "photo"),
        "message_files": storage.delete_tree(root / "messages"),
    }
    detail["voice_samples"] = db.execute(delete(VoiceSample).where(VoiceSample.user_id == user.id)).rowcount
    db.execute(delete(VoiceProfile).where(VoiceProfile.user_id == user.id))
    db.execute(delete(Photo).where(Photo.user_id == user.id))
    message_ids = db.scalars(select(Message.id).where(Message.user_id == user.id)).all()
    detail["messages"] = len(message_ids)
    # 대본 텍스트는 악용 추적을 위한 생성 로그로 남기고, 영상·음성은 지운다
    db.execute(
        update(Message)
        .where(Message.user_id == user.id)
        .values(status="deleted", audio_path=None, video_path=None, poster_path=None, captions=None)
    )
    detail["revoked_links"] = db.execute(
        update(ShareLink).where(ShareLink.message_id.in_(message_ids), ShareLink.revoked.is_(False)).values(revoked=True)
    ).rowcount
    db.execute(
        update(Job).where(Job.user_id == user.id, Job.status == "queued").values(status="canceled", finished_at=utcnow())
    )
    db.execute(
        update(Consent).where(Consent.user_id == user.id, Consent.withdrawn_at.is_(None)).values(withdrawn_at=utcnow())
    )
    db.add(DeletionLog(user_id=user.id, reason="consent_withdrawn", detail=detail))
    db.commit()
    return {"ok": True, "deleted": detail}


@router.get("/parent")
def get_parent(user: User = Depends(current_user)):
    return serialize.parent(user.parent)


class ParentIn(BaseModel):
    nickname: str = Field(min_length=1, max_length=20)
    relation: str = Field(min_length=1, max_length=20)
    phone: str = Field(min_length=9, max_length=20)
    tone_examples: str = Field(default="", max_length=500)


@router.put("/parent")
def put_parent(body: ParentIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    digits = re.sub(r"\D", "", body.phone)
    if not re.fullmatch(r"01\d{8,9}", digits):
        raise HTTPException(400, "휴대폰 번호를 확인해 주세요. (예: 010-1234-5678)")
    phone = f"{digits[:3]}-{digits[3:-4]}-{digits[-4:]}"
    profile = user.parent or ParentProfile(user_id=user.id)
    profile.nickname = body.nickname.strip()
    profile.relation = body.relation.strip()
    profile.phone = phone
    profile.tone_examples = body.tone_examples.strip()
    db.add(profile)
    db.commit()
    db.refresh(user)
    return serialize.parent(user.parent)
