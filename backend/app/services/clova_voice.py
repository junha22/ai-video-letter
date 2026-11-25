"""CLOVA Voice Premium TTS (네이버 클라우드): 타임 슬립(어린 시절 모드)에서 고르는 아이 목소리.
API: https://api.ncloud-docs.com/docs/ai-naver-clovavoice-ttspremium

내 목소리를 변환해서는 아이처럼 들리지 않았다 (Praat·WORLD·Seed-VC 모두 '목소리 높은 어른', docs/YOUNG_MODE.md '목소리 비교').
그래서 진짜 아이 목소리 TTS를 고를 수 있게 했다. 내 목소리가 아니라 정해진 아이 목소리로 대본을 읽는다.
대본 텍스트를 네이버 클라우드로 보낸다 (대본 생성도 이미 네이버 HyperCLOVA X를 쓴다).
글자 사용량은 월 100만 자까지 무료지만 Application을 등록하면 매달 기본료가 붙는다. 안 쓸 때는 콘솔에서 Application을 지운다.
"""

from pathlib import Path

import httpx

from ..config import log, settings
from . import audio, korean

URL = "https://naveropenapi.apigw.ntruss.com/tts-premium/v1/tts"
# 문서의 한국어 아동 목소리 중 사람 목소리 두 개 (가람·야옹이·멍멍이도 있다). 둘 다 감정(emotion) 옵션은 지원하지 않는다
SPEAKERS = {"nhajun": "남자아이 (하준)", "ndain": "여자아이 (다인)"}


class ClovaVoiceError(Exception):
    user_message = "아이 목소리를 만들지 못했어요. 잠시 뒤 다시 시도해 주세요."

    def __init__(self, message: str, retryable: bool = True):
        super().__init__(message)
        self.retryable = retryable  # False면 작업 큐가 재시도하지 않는다 (키·입력 문제)


def available() -> bool:
    return bool(settings.clova_voice_client_id and settings.clova_voice_client_secret)


def synthesize(text: str, speaker: str, out_wav: Path) -> None:
    """대본을 아이 목소리로 읽어 out_wav(24kHz 모노 16비트)로 저장한다. 대본은 로그에 남기지 않는다."""
    headers = {
        "X-NCP-APIGW-API-KEY-ID": settings.clova_voice_client_id,
        "X-NCP-APIGW-API-KEY": settings.clova_voice_client_secret,
    }
    # 숫자·날짜는 우리 TTS와 같게 한글 읽기로 바꿔 보낸다
    data = {"speaker": speaker, "text": korean.numbers_to_hangul(text), "format": "wav", "sampling-rate": 24000}
    try:
        resp = httpx.post(URL, headers=headers, data=data, timeout=httpx.Timeout(60, connect=5))
    except httpx.HTTPError as e:
        raise ClovaVoiceError(f"CLOVA Voice 연결 실패: {type(e).__name__}") from e
    log.info("CLOVA Voice %s -> %s", speaker, resp.status_code)
    if resp.status_code != 200:
        # 400(입력·목소리 이름), 401·403(키), 429(콘솔에서 이 API를 고르지 않음)은 다시 해도 같다
        raise ClovaVoiceError(f"CLOVA Voice 오류 ({resp.status_code}): {resp.text[:300]}", retryable=resp.status_code >= 500)
    # 문서에 WAV 비트 깊이가 없어서 우리 형식으로 맞춘다 (영상·자막 단계는 16비트 WAV를 읽는다)
    audio.run_ffmpeg(["-y", "-i", "pipe:0", "-ac", "1", "-ar", str(audio.SAMPLE_RATE), "-c:a", "pcm_s16le", str(out_wav)],
                     input_bytes=resp.content)
