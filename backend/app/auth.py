"""Signed HttpOnly cookies backed by revocable, hashed server sessions."""

import base64
import hashlib
import hmac
import json
import re
import secrets
import time
from datetime import timedelta
from urllib.parse import urlsplit

from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db, utcnow
from .models import AccountCredential, AuthSession, User

COOKIE = "ongi_session"
PASSWORD_MIN = 4
PBKDF2_ITERATIONS = 600_000
# OWASP Password Storage Cheat Sheet: PBKDF2-HMAC-SHA256 >= 600,000 iterations.
# https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(data: str) -> bytes:
    return base64.b64decode(data + "=" * (-len(data) % 4), altchars=b"-_", validate=True)


def sign(payload) -> str:
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    return f"{body}.{_b64(hmac.new(settings.session_secret.encode(), body.encode(), hashlib.sha256).digest())}"


def verify(token: str) -> dict | None:
    try:
        if not isinstance(token, str) or len(token) > 2048:
            return None
        body, signature = token.split(".")
        expected = _b64(hmac.new(settings.session_secret.encode(), body.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(expected, signature):
            return None
        payload = json.loads(_unb64(body))
        if (not isinstance(payload, dict) or type(payload.get("uid")) is not int or not 0 < payload["uid"] < 2**63
                or type(payload.get("exp")) is not int or payload["exp"] <= time.time()
                or not isinstance(payload.get("sid"), str) or not re.fullmatch(r"[a-f0-9]{64}", payload["sid"])):
            return None
        return payload
    except (ValueError, TypeError, UnicodeError):
        return None


def token_hash(sid: str) -> str:
    return hashlib.sha256(sid.encode()).hexdigest()


def set_session(response: Response, user_id: int, db: Session, method: str = "password") -> None:
    now = utcnow()
    max_age = settings.session_days * 86400
    sid = secrets.token_hex(32)
    db.execute(delete(AuthSession).where(AuthSession.expires_at <= now))
    db.add(AuthSession(user_id=user_id, token_hash=token_hash(sid), auth_method=method,
                       expires_at=now + timedelta(seconds=max_age)))
    db.commit()
    response.set_cookie(COOKIE, sign({"uid": user_id, "sid": sid, "exp": int(time.time()) + max_age}),
                        max_age=max_age, httponly=True, samesite="lax", secure=settings.cookie_secure, path="/")
    response.headers["Cache-Control"] = "private, no-store"


def clear_session(response: Response) -> None:
    response.delete_cookie(COOKIE, path="/", httponly=True, samesite="lax", secure=settings.cookie_secure)
    response.headers["Cache-Control"] = "private, no-store"


def session_for_request(request: Request, db: Session) -> AuthSession | None:
    payload = verify(request.cookies.get(COOKIE, ""))
    if not payload:
        return None
    return db.scalar(select(AuthSession).where(
        AuthSession.user_id == payload["uid"], AuthSession.token_hash == token_hash(payload["sid"]),
        AuthSession.revoked_at.is_(None), AuthSession.expires_at > utcnow(),
    ))


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    session = session_for_request(request, db)
    user = db.get(User, session.user_id) if session else None
    if not user:
        raise HTTPException(401, "로그인이 필요해요.")
    request.state.auth_method = session.auth_method
    return user


def revoke_sessions(db: Session, user_id: int) -> None:
    db.execute(update(AuthSession).where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
               .values(revoked_at=utcnow()))


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${_b64(salt)}${_b64(derived)}"


def check_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt, expected = encoded.split("$")
        if algorithm != "pbkdf2_sha256" or int(iterations) != PBKDF2_ITERATIONS:
            return False
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), _unb64(salt), int(iterations))
        return hmac.compare_digest(candidate, _unb64(expected))
    except (ValueError, TypeError, UnicodeError):
        return False


# A nonexistent email takes the same expensive comparison as an existing account.
DUMMY_HASH = hash_password("non-account timing comparison password")


def credential_for(db: Session, user_id: int) -> AccountCredential | None:
    return db.scalar(select(AccountCredential).where(AccountCredential.user_id == user_id))


def user_info(db: Session, user: User) -> dict:
    credential = credential_for(db, user.id)
    kakao = bool(user.kakao_id and not user.kakao_id.startswith("dev:"))
    return {"id": user.id, "name": user.name, "email": credential.email if credential else None,
            "has_password": credential is not None, "kakao": kakao,
            "auth_method": "password" if credential else "kakao" if kakao else "dev"}


def check_origin(request: Request) -> None:
    """Reject browser cross-origin mutations; CLI clients may omit browser headers."""
    if request.headers.get("sec-fetch-site") == "cross-site":
        raise HTTPException(403, "다른 사이트에서 보낸 요청은 처리할 수 없어요.")
    origin = request.headers.get("origin")
    if origin is None:
        return
    def canonical(value: str) -> tuple:
        parsed = urlsplit(value)
        if (parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username
                or parsed.password or parsed.query or parsed.fragment or parsed.path not in ("", "/")):
            raise ValueError
        return parsed.scheme, parsed.hostname.lower(), parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        allowed = {canonical(settings.public_base_url), canonical(str(request.base_url))}
        if canonical(origin) in allowed:
            return
    except ValueError:
        pass
    raise HTTPException(403, "다른 사이트에서 보낸 요청은 처리할 수 없어요.")
