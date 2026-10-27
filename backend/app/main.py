import logging
import re
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

from .auth import check_origin

from .config import settings
from .db import init_db
from .routers import account, auth, conversations, messages, notifications, photo, voice, watch
from .services import s3gen, wemeet_tts

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


class _HideShareTokens(logging.Filter):
    """공유 링크 토큰은 로그인 없이 대화방에 들어가는 열쇠라서 접속 로그(클라우드 로그 저장소)에 남기지 않는다."""

    pattern = re.compile(r"(/api/watch/)[^/?\s]+")

    def filter(self, record: logging.LogRecord) -> bool:
        # uvicorn 접속 로그의 args: (클라이언트, 메서드, 경로, HTTP 버전, 상태)
        if isinstance(record.args, tuple) and len(record.args) > 2 and isinstance(record.args[2], str):
            record.args = (*record.args[:2], self.pattern.sub(r"\1***", record.args[2]), *record.args[3:])
        return True


logging.getLogger("uvicorn.access").addFilter(_HideShareTokens())


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(title="온기 API", lifespan=lifespan)


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, error: RequestValidationError):
    # Validation errors can contain submitted input, including plaintext passwords.
    if request.url.path.startswith("/api/auth/"):
        return JSONResponse({"detail": "입력한 내용을 확인해 주세요. 이메일 형식과 비밀번호 길이(4자 이상)를 확인해 주세요."}, status_code=422)
    details = [{"loc": item["loc"], "msg": item["msg"], "type": item["type"]} for item in error.errors()]
    return JSONResponse({"detail": details}, status_code=422)


@app.middleware("http")
async def mutation_origin(request: Request, call_next):
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        try:
            check_origin(request)
        except HTTPException as error:
            return JSONResponse({"detail": error.detail}, status_code=error.status_code)
    response = await call_next(request)
    if request.url.path.startswith(("/api/auth", "/api/me")):
        response.headers["Cache-Control"] = "private, no-store"
    return response

for module in (auth, account, voice, photo, messages, watch, notifications, conversations):
    app.include_router(module.router)


@app.get("/api/health")
def health():
    status = {
        "ok": True,
        "tts_provider": settings.tts_provider,
        "video_provider": settings.video_provider,
        "llm": "hyperclova-x" if settings.naver_api_key else "fallback",
        "kakao_login": bool(settings.kakao_rest_api_key),
    }
    if settings.tts_provider == "wemeet":
        # GPU를 쓰지 않는 상태 확인이라 워커 큐를 거치지 않고 바로 묻는다
        status["tts_server"] = "ok" if wemeet_tts.health() else "unreachable"
        status["s3gen_training"] = (s3gen.unavailable_reason() or "on") if settings.s3gen_training else "off"
    return status
