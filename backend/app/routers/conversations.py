"""Authenticated recipient inbox, daily archive and monthly reply portfolios."""

import re
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import current_user
from ..config import settings
from ..db import get_db
from ..models import ParentProfile, Recipient, SeniorReply, User
from ..services import conversations as service
from ..services import replies, storage

router = APIRouter(prefix="/api", tags=["conversations"])


class RecipientIn(BaseModel):
    nickname: str = Field(min_length=1, max_length=20)
    relation: str = Field(min_length=1, max_length=20)
    phone: str = Field(default="", max_length=20)
    child_call_name: str = Field(default="", max_length=20)
    speech_level: Literal["", "반말", "존댓말"] = ""
    tone_examples: str = Field(default="", max_length=500)

    @field_validator("nickname", "relation", "child_call_name", "tone_examples", mode="before")
    @classmethod
    def trim(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("phone")
    @classmethod
    def phone_number(cls, value: str) -> str:
        if not value.strip():
            return ""
        digits = re.sub(r"\D", "", value)
        if not re.fullmatch(r"01\d{8,9}", digits):
            raise ValueError("휴대폰 번호를 확인해 주세요. (예: 010-1234-5678)")
        return f"{digits[:3]}-{digits[3:-4]}-{digits[-4:]}"


@router.get("/recipients")
def list_recipients(user: User = Depends(current_user), db: Session = Depends(get_db)):
    service.ensure_primary(db, user)
    db.commit()
    rows = db.scalars(select(Recipient).where(Recipient.user_id == user.id).order_by(Recipient.id)).all()
    stats = service.recipient_summaries(db, rows)
    results = [service.recipient_dict(db, recipient, stats=stats[recipient.id]) for recipient in rows]
    results.sort(key=lambda item: (item["last_activity_at"] or "", -item["id"]), reverse=True)
    return results


@router.post("/recipients", status_code=201)
def create_recipient(body: RecipientIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    primary = service.ensure_primary(db, user)
    if primary is None:
        # Keep the existing onboarding /parent and generation preconditions working.
        profile = ParentProfile(user_id=user.id, **body.model_dump())
        db.add(profile)
        db.flush()
        db.expire(user, ["parent"])
        recipient = service.ensure_primary(db, user)
    else:
        count = len(db.scalars(select(Recipient.id).where(Recipient.user_id == user.id)).all())
        if count >= 50:
            raise HTTPException(409, "대화 대상자는 최대 50명까지 등록할 수 있어요.")
        recipient = Recipient(user_id=user.id, **body.model_dump())
        db.add(recipient)
    db.commit()
    return service.recipient_dict(db, recipient)


@router.get("/recipients/{recipient_id}")
def get_recipient(recipient_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    recipient = service.owned_recipient(db, user, recipient_id)
    db.commit()
    return service.recipient_dict(db, recipient)


@router.put("/recipients/{recipient_id}")
def update_recipient(recipient_id: int, body: RecipientIn,
                     user: User = Depends(current_user), db: Session = Depends(get_db)):
    recipient = service.owned_recipient(db, user, recipient_id)
    for key, value in body.model_dump().items():
        setattr(recipient, key, value)
    if recipient.legacy_parent_id:
        profile = db.get(ParentProfile, recipient.legacy_parent_id)
        for key, value in body.model_dump().items():
            setattr(profile, key, value)
    db.commit()
    return service.recipient_dict(db, recipient)


@router.get("/conversations/{recipient_id}")
def get_conversation(recipient_id: int, response: Response, date: str | None = None,
                     before: str | None = None, limit: int = Query(default=100, ge=1, le=200),
                     user: User = Depends(current_user), db: Session = Depends(get_db)):
    recipient = service.owned_recipient(db, user, recipient_id)
    db.commit()
    response.headers["Cache-Control"] = "private, no-store"
    return service.conversation(db, recipient, date, before=before, limit=limit)


@router.get("/conversations/{recipient_id}/feed")
def get_conversation_feed(recipient_id: int, response: Response, before: str | None = None, after: str | None = None,
                          user: User = Depends(current_user), db: Session = Depends(get_db)):
    """대화방 채팅: 대화가 있는 날 며칠씩 (처음엔 최근 며칠, before=그 앞 며칠, after=그 뒤 며칠)."""
    recipient = service.owned_recipient(db, user, recipient_id)
    db.commit()
    response.headers["Cache-Control"] = "private, no-store"
    return service.conversation_feed(db, recipient, before=before, after=after)


@router.delete("/recipients/{recipient_id}/replies/{reply_id}")
def delete_reply(recipient_id: int, reply_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    recipient = service.owned_recipient(db, user, recipient_id)
    service.delete_reply(db, recipient, reply_id)
    return {"ok": True}


# ---------------------------------------------------------------- 음성 답장·답장 분석 (docs/REPLY_ANALYSIS.md) ----
@router.get("/recipients/{recipient_id}/replies/{reply_id}/audio")
def reply_audio(recipient_id: int, reply_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    recipient = service.owned_recipient(db, user, recipient_id)
    reply = db.get(SeniorReply, reply_id)
    if (not reply or reply.kind != "voice" or reply.user_id != user.id or reply.recipient_id != recipient.id
            or not reply.audio_path or not storage.abs_path(reply.audio_path).exists()):
        raise HTTPException(404, "음성 답장을 찾을 수 없어요.")
    return FileResponse(storage.abs_path(reply.audio_path), media_type="audio/wav",
                        headers={"Cache-Control": "private, no-store"})


def _analysis_feature() -> None:
    if not settings.reply_analysis_enabled:
        raise HTTPException(404)


@router.post("/recipients/{recipient_id}/replies/{reply_id}/analysis")
def retry_analysis(recipient_id: int, reply_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """정리하지 못한 답장 다시 정리하기 (GPU PC가 꺼져 있었을 때 등)"""
    _analysis_feature()
    recipient = service.owned_recipient(db, user, recipient_id)
    row = replies.retry(db, recipient, reply_id)
    db.commit()
    return replies.serialize(row)


class ReplyAnalysisIn(BaseModel):
    enabled: bool
    agree: bool = False  # 켤 때: 부모님께 알리고 동의를 받았다는 확인


@router.get("/recipients/{recipient_id}/reply-analysis")
def get_reply_analysis(recipient_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _analysis_feature()
    recipient = service.owned_recipient(db, user, recipient_id)
    db.commit()
    return replies.owner_state(db, recipient)


@router.put("/recipients/{recipient_id}/reply-analysis")
def set_reply_analysis(recipient_id: int, body: ReplyAnalysisIn, user: User = Depends(current_user),
                       db: Session = Depends(get_db)):
    """대상자별 답장 살펴보기 켜기·끄기. 끄면 분석 결과·분석 알림을 지운다 (답장과 음성은 남긴다)"""
    _analysis_feature()
    recipient = service.owned_recipient(db, user, recipient_id)
    service.lock_owner(db, user.id)
    if body.enabled:
        if not body.agree:
            raise HTTPException(400, "부모님께 알리고 동의를 받았는지 확인해 주세요.")
        replies.agree(db, recipient, "child")
    else:
        replies.turn_off(db, recipient)
    db.commit()
    return replies.owner_state(db, recipient)


@router.get("/recipients/{recipient_id}/portfolio")
def get_portfolio(recipient_id: int, response: Response, month: str | None = None,
                  user: User = Depends(current_user), db: Session = Depends(get_db)):
    recipient = service.owned_recipient(db, user, recipient_id)
    db.commit()
    response.headers["Cache-Control"] = "private, no-store"
    return service.portfolio_state(db, recipient, month)


@router.post("/recipients/{recipient_id}/portfolio")
def generate_portfolio(recipient_id: int, response: Response, month: str | None = None,
                       user: User = Depends(current_user), db: Session = Depends(get_db)):
    recipient = service.owned_recipient(db, user, recipient_id)
    response.headers["Cache-Control"] = "private, no-store"
    return service.portfolio_state(db, recipient, month, generate=True)
