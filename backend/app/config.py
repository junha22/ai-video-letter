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
    video_a_cfg_scale = _optional("VIDEO_A_CFG_SCALE", float)
    video_e_cfg_scale = _optional("VIDEO_E_CFG_SCALE", float)
    video_seed = _optional("VIDEO_SEED", int)
    # 사진 충실도와 눈 후처리 (backend/gpu_worker/float_tuning.py)
    video_r_cfg_scale = _optional("VIDEO_R_CFG_SCALE", float)
    video_ref_mode = os.getenv("VIDEO_REF_MODE", "").strip().lower()
    video_eye_stable = _optional("VIDEO_EYE_STABLE", float)
    video_blink_gap = _optional("VIDEO_BLINK_GAP", float)
    video_dejump = _bool("VIDEO_DEJUMP", default=False) if os.getenv("VIDEO_DEJUMP", "").strip() else None

    # TTS_PROVIDER=wemeet: 우리가 학습한 한국어 TTS 서버 (C:\WE_MEET\tts_server)
    wemeet_tts_url = os.getenv("WEMEET_TTS_URL", "http://127.0.0.1:8100").rstrip("/")
    wemeet_tts_api_key = os.getenv("WEMEET_TTS_API_KEY", "")
    wemeet_tts_timeout = _float("WEMEET_TTS_TIMEOUT", 300.0)

    # S3GEN_TRAINING=true: 목소리 등록 뒤 녹음으로 사용자별 S3Gen 음색 어댑터를 학습하고, 더 닮았을 때만 적용한다 (wemeet 전용)
    # 학습은 torch가 있는 Wemeet-cb 환경 python으로 연구 코드(AI_test/chatterbox_lora)를 실행한다
    s3gen_training = _bool("S3GEN_TRAINING", default=False)
    wemeet_train_python = os.getenv("WEMEET_TRAIN_PYTHON", "")
    wemeet_lora_code_dir = os.getenv("WEMEET_LORA_CODE_DIR") or str(BACKEND_DIR.parent.parent / "AI_test")
    # RTX 4070 12GB에서 TTS 서버(3.1GB)를 켠 채로 배치 4가 최대 약 9GB, 1000 step에 약 3.5분 (배치 8은 12GB 한계에 닿는다)
    s3gen_steps = int(os.getenv("S3GEN_STEPS", "1000"))
    s3gen_batch_size = int(os.getenv("S3GEN_BATCH_SIZE", "4"))
    # 적용 기준: 어댑터 쪽 화자 유사도가 VoiceEncoder로 이만큼 오르고, WavLM으로 이만큼 이상일 때 (임시값, 연구 쪽 결정 대기)
    s3gen_min_ve_gain = _float("S3GEN_MIN_VE_GAIN", 0.005)
    s3gen_min_sv_gain = _float("S3GEN_MIN_SV_GAIN", 0.0)

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
