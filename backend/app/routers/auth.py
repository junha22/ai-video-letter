import secrets
import hashlib
import re
from datetime import timedelta
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..auth import (DUMMY_HASH, PASSWORD_MIN, check_password, clear_session,
                    credential_for, current_user, hash_password, revoke_sessions,
                    session_for_request, set_session, user_info)
from ..config import log, settings
from ..db import get_db, utcnow
from ..models import AccountCredential, AuthRateLimit, User
from ..services.conversations import lock_owner

router = APIRouter(prefix="/api/auth", tags=["auth"])

STATE_COOKIE = "ongi_oauth_state"


def _redirect_uri() -> str:
    return f"{settings.public_base_url}/api/auth/kakao/callback"


@router.get("/config")
def auth_config():
    return {"kakao": bool(settings.kakao_rest_api_key), "dev_login": settings.dev_login,
            "password_login": True, "password_min_length": PASSWORD_MIN, "password_max_length": None}


def _limit(db: Session, request: Request, action: str, email: str | None = None) -> None:
    """Atomic shared fixed-window limits. Do not trust client-supplied forwarding headers."""
    now = utcnow()
    db.execute(delete(AuthRateLimit).where(AuthRateLimit.expires_at <= now))
    ip = request.client.host if request.client else "unknown"
    scopes = [(f"{action}:ip:{ip}", 30 if action == "login" else 10)]
    if email:
        scopes.append((f"{action}:email:{email}", 10))
    exceeded = False
    for scope, maximum in scopes:
        key = hashlib.sha256(scope.encode()).hexdigest()
        if db.bind.dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import insert
        else:
            from sqlalchemy.dialects.sqlite import insert
        statement = insert(AuthRateLimit).values(key=key, attempts=1, expires_at=now + timedelta(minutes=15))
        statement = statement.on_conflict_do_update(index_elements=[AuthRateLimit.key],
                                                    set_={"attempts": AuthRateLimit.attempts + 1})
        count = db.execute(statement.returning(AuthRateLimit.attempts)).scalar_one()
        exceeded = exceeded or count > maximum
    db.commit()
    if exceeded:
        raise HTTPException(429, "시도가 너무 많아요. 15분 후 다시 시도해 주세요.", headers={"Retry-After": "900"})


def _next(db: Session, user: User) -> str:
    from ..serialize import me
    state = me(db, user)
    if not state["consent_ok"]:
        return "/onboarding/consent"
    if not state["parent"]:
        return "/onboarding/parent"
    if state["voice"]["status"] in ("none", "recording", "failed"):
        return "/onboarding/voice"
    if not state["photo"]:
        return "/onboarding/photo"
    return "/home"


def _authenticated(db: Session, user: User, method: str = "password") -> JSONResponse:
    response = JSONResponse({"ok": True, "user": user_info(db, user), "next": _next(db, user)})
    set_session(response, user.id, db, method)
    return response


class EmailIn(BaseModel):
    model_config = ConfigDict(strict=True)
    email: str = Field(min_length=3, max_length=254)

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value):
        if not isinstance(value, str):
            raise ValueError("이메일을 입력해 주세요.")
        value = value.strip().lower()
        if (not re.fullmatch(r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+", value)
                or len(value.split("@")[0]) > 64 or value.startswith(".") or ".@" in value or ".." in value):
            raise ValueError("올바른 이메일 주소를 입력해 주세요.")
        return value


class CredentialsIn(EmailIn):
    password: str = Field(min_length=PASSWORD_MIN)

    @field_validator("password")
    @classmethod
    def password_valid(cls, value: str) -> str:
        try:
            value.encode("utf-8")
        except UnicodeError:
            raise ValueError("비밀번호의 문자를 확인해 주세요.")
        return value


class RegisterIn(CredentialsIn):
    name: str = Field(min_length=1, max_length=50)

    @field_validator("name", mode="before")
    @classmethod
    def name_valid(cls, value):
        if not isinstance(value, str):
            raise ValueError("이름을 입력해 주세요.")
        return value.strip()


class LoginIn(EmailIn):
    password: str = Field(min_length=1)


class PasswordIn(BaseModel):
    model_config = ConfigDict(strict=True)
    current_password: str = Field(min_length=1)
    new_password: str = Field(min_length=PASSWORD_MIN)

    @field_validator("new_password")
    @classmethod
    def password_valid(cls, value):
        return CredentialsIn.password_valid(value)


@router.post("/register")
def register(body: RegisterIn, request: Request, db: Session = Depends(get_db)):
    _limit(db, request, "register")
    encoded = hash_password(body.password)
    try:
        user = User(name=body.name)
        db.add(user)
        db.flush()
        db.add(AccountCredential(user_id=user.id, email=body.email, password_hash=encoded))
        db.flush()
        return _authenticated(db, user)
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "이미 사용 중인 이메일이에요. 로그인해 주세요.")


@router.post("/login")
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    _limit(db, request, "login", body.email)
    credential = db.scalar(select(AccountCredential).where(AccountCredential.email == body.email))
    checked_hash = credential.password_hash if credential else DUMMY_HASH
    if not check_password(body.password, checked_hash) or not credential:
        raise HTTPException(401, "이메일 또는 비밀번호를 확인해 주세요.")
    uid = credential.user_id
    lock_owner(db, uid)
    db.expire_all()
    credential = credential_for(db, uid)
    if not credential or credential.password_hash != checked_hash:
        raise HTTPException(401, "이메일 또는 비밀번호를 확인해 주세요.")
    return _authenticated(db, db.get(User, uid))


@router.post("/credentials")
def attach_credentials(body: CredentialsIn, request: Request,
                       user: User = Depends(current_user), db: Session = Depends(get_db)):
    _limit(db, request, "credentials")
    encoded = hash_password(body.password)
    lock_owner(db, user.id)
    db.expire_all()
    if not session_for_request(request, db):
        raise HTTPException(401, "다시 로그인해 주세요.")
    if credential_for(db, user.id):
        raise HTTPException(409, "이미 이메일이 연결된 계정이에요.")
    try:
        db.add(AccountCredential(user_id=user.id, email=body.email, password_hash=encoded))
        db.flush()
        revoke_sessions(db, user.id)
        return _authenticated(db, user)
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "이미 사용 중인 이메일이에요.")


@router.post("/password")
def change_password(body: PasswordIn, request: Request,
                    user: User = Depends(current_user), db: Session = Depends(get_db)):
    _limit(db, request, "password")
    credential = credential_for(db, user.id)
    checked_hash = credential.password_hash if credential else DUMMY_HASH
    if not check_password(body.current_password, checked_hash) or not credential:
        raise HTTPException(401, "현재 비밀번호를 확인해 주세요.")
    encoded = hash_password(body.new_password)
    lock_owner(db, user.id)
    db.expire_all()
    credential = credential_for(db, user.id)
    if not session_for_request(request, db) or not credential or credential.password_hash != checked_hash:
        raise HTTPException(401, "다시 로그인해 주세요.")
    credential.password_hash = encoded
    revoke_sessions(db, user.id)
    return _authenticated(db, user)


@router.get("/kakao/login")
def kakao_login():
    if not settings.kakao_rest_api_key:
        raise HTTPException(400, "카카오 로그인이 설정되지 않았어요 (KAKAO_REST_API_KEY).")
    state = secrets.token_urlsafe(16)
    query = urlencode(
        {"client_id": settings.kakao_rest_api_key, "redirect_uri": _redirect_uri(), "response_type": "code", "state": state}
    )
    response = RedirectResponse(f"https://kauth.kakao.com/oauth/authorize?{query}")
    response.set_cookie(STATE_COOKIE, state, max_age=600, httponly=True, samesite="lax", secure=settings.cookie_secure)
    return response


@router.get("/kakao/callback")
def kakao_callback(request: Request, code: str | None = None, state: str | None = None, db: Session = Depends(get_db)):
    fail = RedirectResponse(f"{settings.public_base_url}/?login_error=1")
    if not code or not state or state != request.cookies.get(STATE_COOKIE):
        return fail
    try:
        token_data = {
            "grant_type": "authorization_code",
            "client_id": settings.kakao_rest_api_key,
            "redirect_uri": _redirect_uri(),
            "code": code,
        }
        if settings.kakao_client_secret:
            token_data["client_secret"] = settings.kakao_client_secret
        token = httpx.post("https://kauth.kakao.com/oauth/token", data=token_data, timeout=10).raise_for_status().json()
        profile = (
            httpx.get(
                "https://kapi.kakao.com/v2/user/me",
                headers={"Authorization": f"Bearer {token['access_token']}"},
                timeout=10,
            )
            .raise_for_status()
            .json()
        )
    except (httpx.HTTPError, KeyError) as e:
        log.warning("카카오 로그인 실패: %s", e)
        return fail

    kakao_id = str(profile["id"])
    nickname = (profile.get("kakao_account", {}).get("profile") or {}).get("nickname") or "사용자"
    user = db.scalar(select(User).where(User.kakao_id == kakao_id))
    if not user:
        user = User(kakao_id=kakao_id, name=nickname[:50])
        db.add(user)
        db.commit()

    response = RedirectResponse(f"{settings.public_base_url}/home")
    response.delete_cookie(STATE_COOKIE)
    set_session(response, user.id, db, "kakao")
    return response


class DevLoginIn(BaseModel):
    name: str = Field(min_length=1, max_length=50)

    @field_validator("name", mode="before")
    @classmethod
    def trimmed_name(cls, value):
        return value.strip() if isinstance(value, str) else value


@router.post("/dev-login")
def dev_login(body: DevLoginIn, request: Request, db: Session = Depends(get_db)):
    """카카오 키가 없을 때 쓰는 개발용 로그인. 같은 이름이면 같은 계정으로 들어간다."""
    if not settings.dev_login:
        raise HTTPException(404)
    _limit(db, request, "dev")
    name = body.name.strip()
    user = db.scalar(select(User).where(User.kakao_id == f"dev:{name}"))
    if not user:
        try:
            with db.begin_nested():
                user = User(kakao_id=f"dev:{name}", name=name)
                db.add(user)
                db.flush()
        except IntegrityError:
            user = db.scalar(select(User).where(User.kakao_id == f"dev:{name}"))
            if user is None:
                raise
    lock_owner(db, user.id)
    db.expire_all()
    if credential_for(db, user.id):
        raise HTTPException(403, "이메일과 비밀번호로 로그인해 주세요.")
    return _authenticated(db, user, "dev")


@router.post("/logout")
def logout(request: Request, db: Session = Depends(get_db)):
    session = session_for_request(request, db)
    if session:
        session.revoked_at = utcnow()
        db.commit()
    response = JSONResponse({"ok": True})
    clear_session(response)
    return response
