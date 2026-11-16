"""GPU PC 답장 분석 서버(gpu_worker/reply_analysis_server.py) 클라이언트: 음성 답장의 받아쓰기·운율 (docs/REPLY_ANALYSIS.md).

같은 PC면 REPLY_ANALYSIS_URL=http://127.0.0.1:8400, Azure에서는 게이트웨이 주소 + /analysis와 게이트웨이 토큰.
워커가 작업을 하나씩 처리하므로 분석 서버에 동시에 요청이 가지 않는다. 음성·받아쓰기·결과는 로그에 남기지 않는다.
LLM 판단은 CLOVA Studio(reply_llm.py)가 한다.
"""

from pathlib import Path

import httpx

from ..config import settings

# 시험에서 가짜 분석 서버(httpx.MockTransport)를 끼워 넣는 자리
transport: httpx.BaseTransport | None = None


class AnalysisError(Exception):
    """retryable=False면 다시 해도 같아서(읽을 수 없는 음성, JSON을 못 만듦) 작업 큐가 바로 실패로 둔다"""

    def __init__(self, message: str, retryable: bool = True):
        super().__init__(message)
        self.retryable = retryable


def _client(timeout: float | None = None) -> httpx.Client:
    headers = {"X-API-Key": settings.reply_analysis_api_key} if settings.reply_analysis_api_key else {}
    return httpx.Client(base_url=settings.reply_analysis_url, headers=headers, transport=transport,
                        timeout=httpx.Timeout(timeout or settings.reply_analysis_timeout, connect=10))


def _call(method: str, path: str, **kwargs) -> dict:
    try:
        with _client() as c:
            r = c.request(method, path, **kwargs)
    except httpx.TimeoutException as e:
        raise AnalysisError(f"답장 분석 서버 응답 시간 초과 ({path})") from e
    except httpx.HTTPError as e:
        raise AnalysisError(f"답장 분석 서버에 연결하지 못했습니다 ({path}, {type(e).__name__})") from e
    if r.status_code != 200:
        try:
            detail = str(r.json().get("detail", ""))[:300]
        except ValueError:
            detail = ""
        # 400·413: 음성을 읽을 수 없거나 너무 큼 → 다시 해도 같다. 401: 토큰 틀림
        raise AnalysisError(f"답장 분석 서버 {path} → {r.status_code} {detail}".strip(), retryable=r.status_code >= 500)
    return r.json()


def health() -> bool:
    try:
        with _client(5) as c:
            return c.get("/health").status_code == 200
    except httpx.HTTPError:
        return False


def stt(wav: Path) -> dict:
    with open(wav, "rb") as f:
        return _call("POST", "/stt", files={"audio": ("reply.wav", f, "audio/wav")})


def prosody(wav: Path, text: str) -> dict:
    with open(wav, "rb") as f:
        return _call("POST", "/prosody", files={"audio": ("reply.wav", f, "audio/wav")}, data={"text": text})
