"""WE_MEET TTS 서버 클라이언트. API 명세는 C:\\WE_MEET\\tts_server\\README.md

서버는 GPU 1장으로 요청을 하나씩 처리하므로, 이 모듈은 작업 워커(app.worker)에서만 부른다.
목소리와 대본은 개인정보라서 로그에는 voice_id, 상태 코드, 걸린 시간만 남긴다.
"""

import time
from dataclasses import dataclass
from pathlib import Path

import httpx

from ..config import log, settings

CONNECT_TIMEOUT = 5.0
CONNECT_RETRIES = (2.0, 4.0)  # 서버가 꺼져 있거나 시작 중일 때 기다렸다가 다시 붙는 간격


class TTSError(Exception):
    retryable = True  # False면 작업 큐가 재시도하지 않고 바로 실패로 기록한다
    user_message: str | None = None


class TTSUnavailable(TTSError):
    """연결 실패, 타임아웃, 5xx. 잠시 뒤 다시 하면 될 수 있다."""

    user_message = "음성 서버에 연결하지 못했어요. 잠시 뒤 다시 시도해 주세요."


class TTSRejected(TTSError):
    """400(입력 문제), 401(API 키). 같은 요청을 다시 보내도 결과가 같다."""

    retryable = False

    def __init__(self, message: str, status: int | None = None, user_message: str | None = None):
        super().__init__(message)
        self.status = status
        if user_message:
            self.user_message = user_message


class VoiceNotFound(TTSRejected):
    """404: 서버에 등록되지 않은 목소리."""


@dataclass
class Speech:
    wav: bytes
    seed: int | None
    audio_seconds: float
    elapsed: float


def _float_header(resp: httpx.Response, name: str) -> float:
    try:
        return float(resp.headers.get(name, 0))
    except ValueError:
        return 0.0


def _request(method: str, path: str, *, read_timeout: float, **kwargs) -> httpx.Response:
    headers = {"X-API-Key": settings.wemeet_tts_api_key} if settings.wemeet_tts_api_key else {}
    timeout = httpx.Timeout(read_timeout, connect=CONNECT_TIMEOUT)
    started = time.monotonic()
    for attempt, wait in enumerate((*CONNECT_RETRIES, None)):
        try:
            resp = httpx.request(method, settings.wemeet_tts_url + path, headers=headers, timeout=timeout, **kwargs)
            break
        except httpx.ConnectError as e:
            # 연결 자체가 안 된 경우만 여기서 다시 붙는다. 읽기 타임아웃은 서버가 아직 처리 중일 수 있어서
            # 바로 다시 보내면 GPU 작업이 두 번 쌓인다. 그 경우는 작업 큐의 재시도(10초, 20초 뒤)에 맡긴다
            if wait is None:
                raise TTSUnavailable(f"TTS 서버 연결 실패 ({settings.wemeet_tts_url}): {e}") from e
            log.warning("TTS 서버 연결 실패, %.0f초 뒤 다시 시도 (%s/%s)", wait, attempt + 1, len(CONNECT_RETRIES))
            time.sleep(wait)
        except httpx.TimeoutException as e:
            raise TTSUnavailable(f"TTS 서버 응답 시간 초과 ({read_timeout:.0f}초)") from e
        except httpx.HTTPError as e:
            raise TTSUnavailable(f"TTS 서버 통신 오류: {type(e).__name__}") from e

    log.info("TTS %s %s -> %s (%.1f초)", method, path, resp.status_code, time.monotonic() - started)
    if resp.status_code < 400:
        return resp
    detail = _detail(resp)
    if resp.status_code == 404:
        raise VoiceNotFound(f"TTS 서버에 등록되지 않은 목소리: {detail}", 404)
    if resp.status_code in (400, 401, 403, 413, 422):
        raise TTSRejected(f"TTS 서버가 요청을 거절함 ({resp.status_code}): {detail}", resp.status_code)
    raise TTSUnavailable(f"TTS 서버 오류 ({resp.status_code}): {detail}")


def _detail(resp: httpx.Response) -> str:
    try:
        return str(resp.json().get("detail", ""))[:300]
    except ValueError:
        return resp.text[:300]


def register_voice(voice_id: str, reference_wav: Path) -> dict:
    """참조 음성 등록. 서버가 앞뒤 무음을 자르고 앞 10초만 쓴다. 같은 voice_id로 다시 보내면 덮어쓴다."""
    with reference_wav.open("rb") as f:
        resp = _request(
            "PUT",
            f"/voices/{voice_id}",
            read_timeout=settings.wemeet_tts_timeout,
            files={"audio": ("ref.wav", f, "audio/wav")},
        )
    return resp.json()


def set_s3gen_adapter(voice_id: str, adapter: Path) -> dict:
    """등록된 목소리에 S3Gen 음색 어댑터를 붙인다. 이후 그 목소리로 만들 때 서버가 자동으로 쓴다.
    서버에는 어댑터만 떼는 API가 없어서, 떼려면 목소리를 지우고 다시 등록해야 한다."""
    with adapter.open("rb") as f:
        resp = _request(
            "PUT",
            f"/voices/{voice_id}/s3gen-adapter",
            read_timeout=settings.wemeet_tts_timeout,
            files={"adapter": ("adapter.safetensors", f, "application/octet-stream")},
        )
    return resp.json()


def synthesize(text: str, voice_id: str, seed: int | None = None) -> Speech:
    """seed를 주면 같은 음성이 다시 나온다. 숫자·날짜·금액은 서버가 한글 읽기로 바꾼다."""
    body = {"text": text, "voice_id": voice_id}
    if seed is not None:
        body["seed"] = seed
    # 생성 시간은 음성 길이와 비슷하다 (8.7초 음성에 약 10초). 넉넉하게 잡고 설정값을 상한으로 둔다
    read_timeout = min(30.0 + len(text) * 1.0, settings.wemeet_tts_timeout)
    resp = _request("POST", "/tts", read_timeout=read_timeout, json=body)
    raw_seed = resp.headers.get("X-Seed")
    return Speech(
        wav=resp.content,
        seed=int(raw_seed) if raw_seed and raw_seed.lstrip("-").isdigit() else None,
        audio_seconds=_float_header(resp, "X-Audio-Seconds"),
        elapsed=_float_header(resp, "X-Elapsed-Seconds"),
    )


def delete_voice(voice_id: str) -> bool:
    """서버에 저장된 참조 음성과 분석 결과를 지운다. 이미 없으면 False."""
    try:
        _request("DELETE", f"/voices/{voice_id}", read_timeout=settings.wemeet_tts_timeout)
    except VoiceNotFound:
        return False
    return True


def health() -> dict | None:
    """서버 상태. 연결되지 않으면 None (재시도 없이 바로 확인)."""
    try:
        resp = httpx.get(f"{settings.wemeet_tts_url}/health", timeout=3.0)
        resp.raise_for_status()
        return resp.json()
    except (httpx.HTTPError, ValueError):
        return None
