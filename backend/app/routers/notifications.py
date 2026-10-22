from fastapi import APIRouter, Depends
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ..auth import current_user
from ..db import get_db, iso, utcnow
from ..models import Notification, User

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.get("")
def list_notifications(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(
        select(Notification).where(Notification.user_id == user.id).order_by(Notification.id.desc()).limit(30)
    ).all()
    unread = db.scalar(
        select(func.count()).where(Notification.user_id == user.id, Notification.read_at.is_(None))
    )
    return {
        "unread": unread,
        "items": [
            {
                "id": n.id,
                "kind": n.kind,
                "text": n.text,
                "message_id": n.message_id,
                "created_at": iso(n.created_at),
                "read": n.read_at is not None,
            }
            for n in rows
        ],
    }


@router.post("/read")
def mark_all_read(user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.execute(
        update(Notification)
        .where(Notification.user_id == user.id, Notification.read_at.is_(None))
        .values(read_at=utcnow())
    )
    db.commit()
    return {"ok": True}
