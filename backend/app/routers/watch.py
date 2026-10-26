"""부모님 시청 페이지용 공개 API. 로그인 없이 만료 기간이 있는 토큰으로만 접근한다."""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db, iso, utcnow
from ..models import Message, Notification, ShareLink
from ..services import script_llm, storage

router = APIRouter(prefix="/api/watch", tags=["watch"])

WATCHABLE = ("approved", "sent", "viewed")


def _link(db: Session, token: str) -> ShareLink:
    link = db.scalar(select(ShareLink).where(ShareLink.token == token))
    if not link or link.message.status not in WATCHABLE + ("deleted",):
        raise HTTPException(404, "영상을 찾을 수 없어요.")
    if link.revoked or link.message.status == "deleted":
        raise HTTPException(410, "더 이상 볼 수 없는 영상이에요.")
    if link.expires_at < utcnow():
        raise HTTPException(410, "링크 기간이 지났어요.")
    return link


@router.get("/{token}")
def watch_info(token: str, db: Session = Depends(get_db)):
    link = _link(db, token)
    m = link.message
    others = db.execute(
        select(ShareLink.token, Message.created_at, Message.script)
        .join(Message, Message.id == ShareLink.message_id)
        .where(
            Message.parent_id == m.parent_id,
            Message.status.in_(WATCHABLE),
            ShareLink.revoked.is_(False),
            ShareLink.expires_at > utcnow(),
            ShareLink.id != link.id,
        )
        .order_by(Message.id.desc())
        .limit(10)
    ).all()
    return {
        "child_name": m.parent.child_name,
        "nickname": m.parent.nickname,
        "created_at": iso(m.created_at),
        "duration": m.duration,
        "captions": m.captions or [],
        "video_url": f"/api/watch/{token}/video",
        "poster_url": f"/api/watch/{token}/poster",
        "expires_at": iso(link.expires_at),
        "others": [{"token": t, "created_at": iso(c), "preview": s[:40]} for t, c, s in others],
    }


def _file(rel: str | None, media_type: str) -> FileResponse:
    if not rel or not storage.abs_path(rel).exists():
        raise HTTPException(404)
    return FileResponse(storage.abs_path(rel), media_type=media_type, headers={"Cache-Control": "private, max-age=3600"})


@router.get("/{token}/video")
def watch_video(token: str, db: Session = Depends(get_db)):
    return _file(_link(db, token).message.video_path, "video/mp4")


@router.get("/{token}/poster")
def watch_poster(token: str, db: Session = Depends(get_db)):
    return _file(_link(db, token).message.poster_path, "image/jpeg")


@router.post("/{token}/viewed")
def mark_viewed(token: str, db: Session = Depends(get_db)):
    link = _link(db, token)
    m = link.message
    link.view_count += 1
    if not link.first_viewed_at:
        link.first_viewed_at = utcnow()
        m.status = "viewed"
        m.viewed_at = link.first_viewed_at
        db.add(
            Notification(
                user_id=m.user_id,
                message_id=m.id,
                kind="viewed",
                text=f"{script_llm.subject(m.parent.nickname)} 영상 편지를 보셨어요",
            )
        )
    db.commit()
    return {"ok": True}
