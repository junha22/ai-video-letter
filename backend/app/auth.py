"""세션 쿠키: HMAC으로 서명한 {uid, exp}. 별도 세션 저장소 없이 동작한다."""

import base64
import hashlib
import hmac
import json
import time

from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import User

COOKIE = "ongi_session"


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def sign(payload: dict) -> str:
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    sig = hmac.new(settings.session_secret.encode(), body.encode(), hashlib.sha256).digest()
    return f"{body}.{_b64(sig)}"


def verify(token: str) -> dict | None:
    try:
        body, sig = token.split(".", 1)
        expected = hmac.new(settings.session_secret.encode(), body.encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(_b64(expected), sig):
            return None
        payload = json.loads(_unb64(body))
    except (ValueError, json.JSONDecodeError):
        return None
    if payload.get("exp", 0) < time.time():
        return None
    return payload


def set_session(response: Response, user_id: int) -> None:
    max_age = settings.session_days * 86400
    response.set_cookie(
        COOKIE,
        sign({"uid": user_id, "exp": int(time.time()) + max_age}),
        max_age=max_age,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )


def clear_session(response: Response) -> None:
    response.delete_cookie(COOKIE, path="/")


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    payload = verify(request.cookies.get(COOKIE, ""))
    user = db.get(User, payload["uid"]) if payload else None
    if not user:
        raise HTTPException(401, "로그인이 필요해요.")
    return user
