import secrets
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import clear_session, set_session
from ..config import log, settings
from ..db import get_db
from ..models import User

router = APIRouter(prefix="/api/auth", tags=["auth"])

STATE_COOKIE = "ongi_oauth_state"


def _redirect_uri() -> str:
    return f"{settings.public_base_url}/api/auth/kakao/callback"


@router.get("/config")
def auth_config():
    return {"kakao": bool(settings.kakao_rest_api_key), "dev_login": settings.dev_login}


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
    set_session(response, user.id)
    return response


class DevLoginIn(BaseModel):
    name: str = Field(min_length=1, max_length=20)


@router.post("/dev-login")
def dev_login(body: DevLoginIn, db: Session = Depends(get_db)):
    """카카오 키가 없을 때 쓰는 개발용 로그인. 같은 이름이면 같은 계정으로 들어간다."""
    if not settings.dev_login:
        raise HTTPException(404)
    name = body.name.strip()
    user = db.scalar(select(User).where(User.kakao_id == f"dev:{name}"))
    if not user:
        user = User(kakao_id=f"dev:{name}", name=name)
        db.add(user)
        db.commit()
    response = JSONResponse({"ok": True})
    set_session(response, user.id)
    return response


@router.post("/logout")
def logout():
    response = JSONResponse({"ok": True})
    clear_session(response)
    return response
