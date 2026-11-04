"""Authenticated recipient inbox, daily archive and monthly reply portfolios."""

import re
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import current_user
from ..db import get_db
from ..models import ParentProfile, Recipient, User
from ..services import conversations as service

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


@router.delete("/recipients/{recipient_id}/replies/{reply_id}")
def delete_reply(recipient_id: int, reply_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    recipient = service.owned_recipient(db, user, recipient_id)
    service.delete_reply(db, recipient, reply_id)
    return {"ok": True}


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
