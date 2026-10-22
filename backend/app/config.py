import logging
import os
import secrets
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
# 실행 위치와 상관없이 backend/.env를 읽는다
load_dotenv(BACKEND_DIR / ".env")

log = logging.getLogger("ongi")


def _bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return default


def _optional(name: str, cast: type) -> float | int | None:
    """비어 있으면 None (= 받는 쪽 기본값을 쓴다)."""
    value = os.getenv(name, "").strip()
    if not value:
        return None
    try:
        return cast(value)
    except ValueError:
        log.warning("%s 값이 올바르지 않아 무시합니다: %r", name, value)
        return None


class Settings:
    data_dir = Path(os.getenv("DATA_DIR") or BACKEND_DIR / "data")
    database_url = os.getenv("DATABASE_URL") or f"sqlite:///{(data_dir / 'ongi.db').as_posix()}"

    public_base_url = os.getenv("PUBLIC_BASE_URL", "http://localhost:3000").rstrip("/")
    session_secret = os.getenv("SESSION_SECRET", "")
    session_days = 30

    kakao_rest_api_key = os.getenv("KAKAO_REST_API_KEY", "")
    kakao_client_secret = os.getenv("KAKAO_CLIENT_SECRET", "")
    dev_login = _bool("DEV_LOGIN", default=not kakao_rest_api_key)

    naver_api_key = os.getenv("NAVER_API_KEY", "")
    hcx_endpoint = os.getenv(
        "HCX_ENDPOINT", "https://clovastudio.stream.ntruss.com/v1/chat-completions/HCX-003"
    )

    tts_provider = os.getenv("TTS_PROVIDER", "local")
    video_provider = os.getenv("VIDEO_PROVIDER", "local")
    runpod_api_key = os.getenv("RUNPOD_API_KEY", "")
    runpod_tts_endpoint_id = os.getenv("RUNPOD_TTS_ENDPOINT_ID", "")
    runpod_video_endpoint_id = os.getenv("RUNPOD_VIDEO_ENDPOINT_ID", "")
    runpod_cost_per_second = _float("RUNPOD_COST_PER_SECOND", 0.0)

    # VIDEO_PROVIDER=runpod일 때 FLOAT 영상 핸들러에 넘기는 옵션 (backend/gpu_worker/video_handler.py).
    # 비워 두면 핸들러 기본값을 쓴다
    video_lora_strength = _optional("VIDEO_LORA_STRENGTH", float)
    video_emotion = os.getenv("VIDEO_EMOTION", "").strip().lower()
    video_a_cfg_scale = _optional("VIDEO_A_CFG_SCALE", float)
    video_e_cfg_scale = _optional("VIDEO_E_CFG_SCALE", float)
    video_seed = _optional("VIDEO_SEED", int)

    voice_target_seconds = int(os.getenv("VOICE_TARGET_SECONDS", "180"))
    reference_seconds = 12
    share_link_days = int(os.getenv("SHARE_LINK_DAYS", "30"))
    job_max_attempts = 3

    @property
    def cookie_secure(self) -> bool:
        return self.public_base_url.startswith("https://")


settings = Settings()

if not settings.session_secret:
    # 개발 편의를 위해 data 폴더에 키를 만들어 둔다. 배포 시에는 SESSION_SECRET을 지정해야 한다
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    secret_file = settings.data_dir / ".session_secret"
    if not secret_file.exists():
        secret_file.write_text(secrets.token_urlsafe(48), encoding="utf-8")
    settings.session_secret = secret_file.read_text(encoding="utf-8").strip()
