import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .config import settings
from .db import init_db
from .routers import account, auth, messages, notifications, photo, voice, watch
from .services import wemeet_tts

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(title="온기 API", lifespan=lifespan)

for module in (auth, account, voice, photo, messages, watch, notifications):
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
    return status
