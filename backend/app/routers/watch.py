"""Unauthenticated recipient rooms authorized only by an active, scoped share token."""

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..db import get_db, iso, utcnow
from ..models import Message, Notification, SeniorReply, ShareLink
from ..services import conversations, script_llm, storage

router = APIRouter(prefix="/api/watch", tags=["watch"])
WATCHABLE = conversations.WATCHABLE


def _link(db: Session, token: str) -> ShareLink:
    if len(token) > 64:
        raise HTTPException(404, "대화방을 찾을 수 없어요.")
    link = db.scalar(select(ShareLink).where(ShareLink.token == token))
    if not link or link.message.status not in WATCHABLE + ("deleted",):
        raise HTTPException(404, "대화방을 찾을 수 없어요.")
    if link.revoked or link.message.status == "deleted":
        raise HTTPException(410, "더 이상 볼 수 없는 대화방이에요.")
    if link.expires_at <= utcnow():
        raise HTTPException(410, "링크 기간이 지났어요. 가족에게 새 링크를 요청해 주세요.")
    if not link.message.recipient or link.message.recipient.user_id != link.message.user_id:
        raise HTTPException(404, "대화방을 찾을 수 없어요.")
    return link


def _room_message(db: Session, link: ShareLink, message_id: int) -> Message:
    message = db.get(Message, message_id)
    if (not message or message.user_id != link.message.user_id
            or message.recipient_id != link.message.recipient_id or message.status not in WATCHABLE):
        raise HTTPException(404, "영상 편지를 찾을 수 없어요.")
    return message


@router.get("/{token}")
def watch_info(token: str, response: Response, db: Session = Depends(get_db)):
    link = _link(db, token)
    message = link.message
    recipient = message.recipient
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return {
        "child_name": recipient.child_name, "nickname": recipient.nickname,
        "created_at": iso(message.created_at), "duration": message.duration,
        "captions": message.captions or [], "video_url": f"/api/watch/{token}/video",
        "poster_url": f"/api/watch/{token}/poster", "expires_at": iso(link.expires_at),
        "conversation_url": f"/api/watch/{token}/conversation", "others": [],
    }


@router.get("/{token}/conversation")
def get_conversation(token: str, response: Response, date: str | None = None, before: str | None = None,
                     limit: int = Query(default=100, ge=1, le=200), db: Session = Depends(get_db)):
    link = _link(db, token)
    result = conversations.conversation(db, link.message.recipient, date, token, before, limit)
    result.update({"expires_at": iso(link.expires_at), "linked_message_id": link.message_id,
                   "linked_date": conversations.korea_date(conversations.video_time(link.message))})
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return result


def _file(rel: str | None, media_type: str) -> FileResponse:
    if not rel or not storage.abs_path(rel).exists():
        raise HTTPException(404)
    return FileResponse(storage.abs_path(rel), media_type=media_type,
                        headers={"Cache-Control": "private, no-store", "Referrer-Policy": "no-referrer"})


@router.get("/{token}/video")
def watch_video(token: str, db: Session = Depends(get_db)):
    return _file(_link(db, token).message.video_path, "video/mp4")


@router.get("/{token}/poster")
def watch_poster(token: str, db: Session = Depends(get_db)):
    return _file(_link(db, token).message.poster_path, "image/jpeg")


@router.get("/{token}/messages/{message_id}/video")
def room_video(token: str, message_id: int, db: Session = Depends(get_db)):
    link = _link(db, token)
    return _file(_room_message(db, link, message_id).video_path, "video/mp4")


@router.get("/{token}/messages/{message_id}/poster")
def room_poster(token: str, message_id: int, db: Session = Depends(get_db)):
    link = _link(db, token)
    return _file(_room_message(db, link, message_id).poster_path, "image/jpeg")


def _mark_viewed(db: Session, link: ShareLink, message: Message) -> dict:
    token, user_id, message_id = link.token, message.user_id, message.id
    conversations.lock_owner(db, user_id)
    db.expire_all()
    link = _link(db, token)
    message = _room_message(db, link, message_id)
    now = utcnow()
    target_link = link if message.id == link.message_id else db.scalar(
        select(ShareLink).where(ShareLink.message_id == message.id)
    )
    if target_link:
        target_link.view_count += 1
        if not target_link.first_viewed_at:
            target_link.first_viewed_at = now
    if not message.viewed_at:
        message.status = "viewed"
        message.viewed_at = now
        db.add(Notification(
            user_id=message.user_id, recipient_id=message.recipient_id, message_id=message.id,
            kind="viewed", text=f"{script_llm.subject(message.recipient.nickname)} 영상 편지를 보셨어요",
        ))
    db.commit()
    return {"ok": True}


@router.post("/{token}/viewed")
def mark_viewed(token: str, db: Session = Depends(get_db)):
    link = _link(db, token)
    return _mark_viewed(db, link, link.message)


@router.post("/{token}/messages/{message_id}/viewed")
def mark_room_viewed(token: str, message_id: int, db: Session = Depends(get_db)):
    link = _link(db, token)
    return _mark_viewed(db, link, _room_message(db, link, message_id))


class ReplyIn(BaseModel):
    text: str = Field(min_length=1, max_length=1000)
    client_id: str = Field(min_length=8, max_length=80, pattern=r"^[a-zA-Z0-9_-]+$")
    message_id: int | None = Field(default=None, gt=0)

    @field_validator("text", mode="before")
    @classmethod
    def trim(cls, value):
        return value.replace("\r\n", "\n").strip() if isinstance(value, str) else value


def _existing_reply(db: Session, recipient_id: int, client_id: str) -> SeniorReply | None:
    return db.scalar(select(SeniorReply).where(
        SeniorReply.recipient_id == recipient_id, SeniorReply.client_id == client_id,
    ))


def _same_request(reply: SeniorReply, body: ReplyIn) -> dict:
    if reply.text != body.text or reply.message_id != body.message_id:
        raise HTTPException(409, "이미 보낸 답글과 내용이 달라요. 새 답글로 보내 주세요.")
    return conversations.reply_event(reply)


@router.post("/{token}/replies")
def create_reply(token: str, body: ReplyIn, response: Response, db: Session = Depends(get_db)):
    link = _link(db, token)
    conversations.lock_owner(db, link.message.user_id)
    db.expire_all()
    link = _link(db, token)
    recipient = link.message.recipient
    if body.message_id:
        _room_message(db, link, body.message_id)
    existing = _existing_reply(db, recipient.id, body.client_id)
    if existing:
        response.headers["Cache-Control"] = "private, no-store"
        return _same_request(existing, body)
    now = utcnow()
    minute_count = db.scalar(select(func.count()).select_from(SeniorReply).where(
        SeniorReply.recipient_id == recipient.id, SeniorReply.created_at >= now - timedelta(minutes=1),
    ))
    _day, start, end = conversations.day_bounds(conversations.korea_date(now))
    day_count = db.scalar(select(func.count()).select_from(SeniorReply).where(
        SeniorReply.recipient_id == recipient.id, SeniorReply.created_at >= start, SeniorReply.created_at < end,
    ))
    if minute_count >= 10 or day_count >= 120:
        raise HTTPException(429, "답글을 여러 번 보내셨어요. 잠시 뒤 다시 보내 주세요.", headers={"Retry-After": "60"})
    try:
        with db.begin_nested():
            reply = SeniorReply(user_id=recipient.user_id, recipient_id=recipient.id, message_id=body.message_id,
                                share_link_id=link.id, client_id=body.client_id, text=body.text, created_at=now)
            db.add(reply)
            db.flush()
    except IntegrityError:
        existing = _existing_reply(db, recipient.id, body.client_id)
        if existing is None:
            raise
        return _same_request(existing, body)
    db.add(Notification(user_id=recipient.user_id, recipient_id=recipient.id,
                        message_id=body.message_id or link.message_id, kind="senior_reply",
                        text=f"{recipient.nickname}님이 답글을 남기셨어요: {body.text[:60]}"))
    db.commit()
    response.headers["Cache-Control"] = "private, no-store"
    return conversations.reply_event(reply)
