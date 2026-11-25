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
    # Name-only access must be explicitly enabled on an isolated development server.
    dev_login = _bool("DEV_LOGIN", default=False)

    # 동의 화면: 목소리·사진의 저장·처리 장소는 배포 환경마다 달라서 환경 변수로 넣는다 (비우면 표시하지 않음).
    # 문구를 바꾸면 CONSENT_VERSION도 바꿔서 누가 어느 문구에 동의했는지 남긴다
    consent_version = os.getenv("CONSENT_VERSION", "2026-10")
    data_processing_notice = os.getenv("DATA_PROCESSING_NOTICE", "").strip()

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
    # GPU가 없는 곳(Azure)의 워커: 학습을 GPU PC의 학습 서버(gpu_worker/trainer.py)에 맡긴다. 게이트웨이 주소 + /train
    # 이때 학습 설정(step·적용 기준)은 GPU PC의 backend/.env를 따른다
    s3gen_remote_url = os.getenv("S3GEN_REMOTE_URL", "").rstrip("/")
    s3gen_remote_key = os.getenv("S3GEN_REMOTE_KEY", "")

    # 어린 시절 모드 (영상 만들 때 고른다). 사진은 GPU PC의 ComfyUI에서 Qwen-Image-2.1 Turbo로 어리게 바꾼다 (docs/YOUNG_MODE.md).
    # 비워 두면 원본 사진을 그대로 쓴다 (GPU 없이 흐름과 목소리 변환을 확인할 때)
    comfyui_url = os.getenv("COMFYUI_URL", "").rstrip("/")
    comfyui_api_key = os.getenv("COMFYUI_API_KEY", "")  # 게이트웨이(/comfy)를 거칠 때 GPU_GATEWAY_TOKEN
    young_age = int(os.getenv("YOUNG_AGE", "6"))
    # '아이 목소리 높이로 맞추기'(praat)를 골랐을 때 맞출 높이(Hz). 원래 목소리가 낮든 높든 이 높이가 된다. 목소리를 바꿀지는 사용자가 고른다
    young_voice_hz = _float("YOUNG_VOICE_HZ", 270)
    # 목소리 울림(포먼트) 배율. 아이는 성도가 짧아 울림이 높다. 너무 올리면 헬륨 목소리가 된다
    young_voice_formant = _float("YOUNG_VOICE_FORMANT", 1.15)
    # 높낮이 폭 배율. 1보다 크면 억양이 커진다. 1.3도 들어 봤지만 나아지지 않아서 원래 억양 그대로 둔다 (docs/YOUNG_MODE.md)
    young_voice_range = _float("YOUNG_VOICE_RANGE", 1.0)
    # 타임 슬립에서 고르는 아이 목소리 TTS (CLOVA Voice Premium, services/clova_voice.py). 비우면 그 선택지가 안 보인다
    # 네이버 클라우드 콘솔 > AI·NAVER API > Application 등록(CLOVA Voice 선택)의 Client ID·Secret. HyperCLOVA X 키와는 별개
    clova_voice_client_id = os.getenv("CLOVA_VOICE_CLIENT_ID", "")
    clova_voice_client_secret = os.getenv("CLOVA_VOICE_CLIENT_SECRET", "")

    # 부모님 답장 분석 (docs/REPLY_ANALYSIS.md). 기본 꺼짐: 꺼져 있으면 음성 답장·분석이 없고 지금과 똑같이 동작한다.
    # 음성 답장의 받아쓰기·운율은 GPU PC의 분석 서버(gpu_worker/reply_analysis_server.py), Azure에서는 게이트웨이 주소 + /analysis
    reply_analysis_enabled = _bool("REPLY_ANALYSIS_ENABLED", default=False)
    reply_analysis_url = os.getenv("REPLY_ANALYSIS_URL", "http://127.0.0.1:8400").rstrip("/")
    reply_analysis_api_key = os.getenv("REPLY_ANALYSIS_API_KEY", "")  # 게이트웨이를 거칠 때 GPU_GATEWAY_TOKEN
    # 받아쓰기는 요청마다 모델을 올렸다 내려서 넉넉하게 기다린다 (게이트웨이는 900초)
    reply_analysis_timeout = _float("REPLY_ANALYSIS_TIMEOUT", 600.0)
    # 자녀 동의·시니어 안내 문구를 바꾸면 이 값도 바꾼다. 지금 버전으로 받은 동의만 인정해서, 바꾸면 다시 묻는다
    # (2026-11-clova: 답장 글을 CLOVA Studio로 보내 분석한다는 내용이 들어감)
    reply_analysis_consent_version = os.getenv("REPLY_ANALYSIS_CONSENT_VERSION", "2026-11-clova")
    # 답장 분석의 LLM 판단: CLOVA Studio HCX-007 (Chat Completions v3, 형식 강제는 HCX-007만). 대본(HCX_ENDPOINT, v1)과 따로 둔다.
    # 키를 비우면 NAVER_API_KEY를 쓴다. Azure에서는 워커가 GPU PC를 거치지 않고 바로 부른다
    reply_llm_endpoint = os.getenv(
        "REPLY_LLM_ENDPOINT", "https://clovastudio.stream.ntruss.com/v3/chat-completions/HCX-007"
    ).rstrip("/")
    reply_llm_api_key = os.getenv("REPLY_LLM_API_KEY", "")
    reply_llm_timeout = _float("REPLY_LLM_TIMEOUT", 60.0)

    # 기본 등록: 이만큼 넘게 읽은 녹음이 하나 있으면 등록해서 바로 zero-shot으로 영상을 만든다 (대본 1문장이 약 8초)
    voice_basic_seconds = _float("VOICE_BASIC_SECONDS", 6.0)
    # 음색 학습(선택)에 필요한 누적 녹음 길이
    voice_target_seconds = int(os.getenv("VOICE_TARGET_SECONDS", "135"))
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
