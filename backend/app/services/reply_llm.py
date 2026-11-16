"""답장 분석의 LLM 판단: CLOVA Studio Chat Completions v3 (HCX-007) + Structured Outputs (docs/REPLY_ANALYSIS.md).

GPU PC가 TTS·영상 서버로 7GB를 쓰고 있어 로컬 SEED 14B는 너무 느려서, 판단만 CLOVA Studio API로 한다 (2026-11-16).
판단 기준(SYSTEM)·JSON 틀(SCHEMA)·옵션(CLOVA_PARAMS)은 reply_analysis.py 그대로 보낸다.
형식 강제(responseFormat)는 HCX-007만 되고 추론과 같이 못 써서 thinking.effort는 none이다. system 메시지는 1개만.

보내는 것: 판단 기준, 자녀 편지, 최근 분석 기록 3개, mask_pii와 이름 가림을 거친 답장 글.
보내지 않는 것: 사용자·대상자 ID, 이메일, 음성 파일, 목소리 값.
로그에는 요청 ID, 상태 코드, 걸린 시간, 토큰 수만 남긴다 (편지·답장·결과는 남기지 않는다).

키·형식 확인 (가짜 답장 한 줄로 한 번 부른다):
  cd backend; python -m app.services.reply_llm --ping
"""

import argparse
import json
import logging
import re
import time
import uuid

import httpx

from ..config import settings
from . import reply_analysis as rules
from .reply_gpu import AnalysisError

log = logging.getLogger("ongi.reply_llm")

# 시험에서 가짜 CLOVA(httpx.MockTransport)를 끼워 넣는 자리
transport: httpx.BaseTransport | None = None
# 연결이 끊기거나 429·5xx면 이만큼(초) 쉬었다가 다시 부른다. 그래도 안 되면 작업 큐가 나중에 다시 한다
RETRY_WAITS = (2, 4)

# CLOVA Studio 약관상 개인정보를 넣지 않는다: 이메일과 DB에 있는 이름을 가린다 (전화번호·계좌번호는 mask_pii가 가린다)
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
# 이름이 아니라 호칭이라 그대로 둔다 ('우리 ' 앞붙임·'님' 뒷붙임은 떼고 비교)
HONORIFICS = {
    "엄마", "아빠", "어머니", "아버지", "어머님", "아버님", "어무이", "아부지", "할머니", "할아버지", "할매", "할배",
    "외할머니", "외할아버지", "친할머니", "친할아버지", "장모", "장인", "장인어른", "시어머니", "시아버지", "이모", "고모",
    "삼촌", "외삼촌", "큰엄마", "큰아빠", "작은엄마", "작은아빠", "부모", "딸", "아들", "큰딸", "작은딸", "막내딸",
    "큰아들", "작은아들", "막내아들", "막내", "첫째", "둘째", "셋째", "손주", "손자", "손녀", "사위", "며느리",
    "언니", "오빠", "누나", "형", "동생", "여보", "당신",
}


def api_key() -> str:
    return settings.reply_llm_api_key or settings.naver_api_key


def model_name() -> str:
    return settings.reply_llm_endpoint.rsplit("/", 1)[-1]


def _is_honorific(word: str) -> bool:
    w = word.replace(" ", "").removeprefix("우리")
    return w in HONORIFICS or w.removesuffix("님") in HONORIFICS


def names_to_hide(*names: str | None) -> list[str]:
    """가릴 이름: 호칭이 아닌 두 글자 이상. 성까지 쓴 한국 이름(3~4자)은 이름만 쓴 경우(뒤 2자)도 가린다"""
    out = set()
    for name in names:
        name = (name or "").strip()
        if len(name) < 2 or _is_honorific(name):
            continue
        out.add(name)
        if re.fullmatch(r"[가-힣]{3,4}", name):
            out.add(name[-2:])
    return sorted(out, key=lambda n: (-len(n), n))  # 긴 이름부터 (김민수 → 민수 순서), 같은 길이는 가나다순


def hide_names(text: str, names: list[str]) -> str:
    text = EMAIL.sub("[이메일]", text)
    for name in names:
        text = text.replace(name, "[이름]")
    return text


def _status_code(r: httpx.Response) -> str:
    try:
        return str((r.json().get("status") or {}).get("code", ""))
    except ValueError:
        return ""


def _sleep(seconds: float) -> None:
    time.sleep(seconds)


def _post(body: dict) -> tuple[dict, str]:
    """CLOVA를 한 번 부른다. 연결 끊김·429·5xx면 잠깐 쉬었다 다시 하고, 키·형식 오류는 바로 실패로 둔다"""
    for attempt in range(len(RETRY_WAITS) + 1):
        request_id = str(uuid.uuid4())
        headers = {"Authorization": f"Bearer {api_key()}", "X-NCP-CLOVASTUDIO-REQUEST-ID": request_id,
                   "Content-Type": "application/json", "Accept": "application/json"}
        started = time.monotonic()
        try:
            with httpx.Client(transport=transport, timeout=httpx.Timeout(settings.reply_llm_timeout, connect=10)) as c:
                r = c.post(settings.reply_llm_endpoint, json=body, headers=headers)
        except httpx.HTTPError as e:
            reason = type(e).__name__
            log.info("CLOVA %s 요청 %s → 연결 실패 %s (%.1f초)", model_name(), request_id, reason, time.monotonic() - started)
        else:
            code = _status_code(r)
            log.info("CLOVA %s 요청 %s → %s %s (%.1f초)", model_name(), request_id, r.status_code, code,
                     time.monotonic() - started)
            if r.status_code == 200 and code == "20000":
                return r.json(), request_id
            if r.status_code in (401, 403):
                raise AnalysisError(f"CLOVA 키가 없거나 틀렸어요 ({r.status_code} {code})", retryable=False)
            if r.status_code == 400:
                raise AnalysisError(f"CLOVA 요청 형식이 맞지 않아요 (400 {code})", retryable=False)
            if r.status_code != 429 and r.status_code < 500:
                raise AnalysisError(f"CLOVA 요청이 실패했어요 ({r.status_code} {code})", retryable=False)
            reason = f"{r.status_code} {code}".strip()
        if attempt == len(RETRY_WAITS):
            raise AnalysisError(f"CLOVA에 연결하지 못했어요 ({reason})")  # 재시도 가능: 작업 큐가 나중에 다시 한다
        log.info("CLOVA 재시도 %s (%s)", attempt + 1, reason)
        _sleep(RETRY_WAITS[attempt])
    raise AssertionError("unreachable")


def analyze(system: str, user: str, schema: dict, params: dict) -> dict:
    """판단 JSON을 받아 check_output까지 본다. JSON이 깨졌거나 틀에 맞지 않으면 seed+1로 한 번만 더 한다"""
    if not api_key():
        raise AnalysisError("CLOVA 키가 없어요 (REPLY_LLM_API_KEY 또는 NAVER_API_KEY)", retryable=False)
    started = time.monotonic()
    tokens = {"prompt_tokens": 0, "completion_tokens": 0}
    problem = ""
    for attempt in range(2):
        body = {"messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                "responseFormat": {"type": "json", "schema": schema},
                **params, "seed": int(params.get("seed", 1)) + attempt}
        data, request_id = _post(body)
        result = data.get("result") or {}
        usage = result.get("usage") or {}
        tokens["prompt_tokens"] += usage.get("promptTokens") or 0
        tokens["completion_tokens"] += usage.get("completionTokens") or 0
        try:
            out = json.loads((result.get("message") or {}).get("content") or "")
            rules.check_output(out)
        except ValueError as e:  # JSONDecodeError도 ValueError. check_output은 틀린 칸 이름만 알린다
            problem = "JSON이 깨짐" if isinstance(e, json.JSONDecodeError) else str(e)
            log.warning("CLOVA 결과를 쓸 수 없음 (요청 %s, %s) → seed+1로 한 번 더", request_id, problem)
            continue
        return {"json": out, "attempts": attempt + 1, "seconds": round(time.monotonic() - started, 1),
                "request_id": request_id, "model": model_name(), **tokens}
    raise AnalysisError(f"CLOVA가 JSON 틀에 맞는 결과를 만들지 못했어요 (두 번 시도, {problem})", retryable=False)


# ---------------------------------------------------------------- 확인 명령 ----
PING_LETTER = "요즘 어떻게 지내세요? 건강은 괜찮으세요?"
PING_REPLY = "요즘 무릎이 조금 아파서 산책을 못 했어. 그래도 밥은 잘 먹고 있어."


def ping() -> int:
    """가짜 답장 한 줄로 키·주소·형식이 맞는지 본다 (실제 답장은 보내지 않는다)"""
    print(f"주소 {settings.reply_llm_endpoint} | 키 {'있음' if api_key() else '없음'} | 판단 기준 {rules.PROMPT_ID}")
    if not api_key():
        print("REPLY_LLM_API_KEY 또는 NAVER_API_KEY를 backend/.env에 넣어 주세요.")
        return 1
    user = rules.user_prompt(PING_LETTER, [], rules.mask_pii(PING_REPLY))
    try:
        r = analyze(rules.SYSTEM, user, rules.SCHEMA, rules.CLOVA_PARAMS)
    except AnalysisError as e:
        print(f"실패: {e} ({'나중에 다시 하면 될 수 있음' if e.retryable else '설정을 고쳐야 함'})")
        return 1
    j = r["json"]
    print(f"성공: {r['seconds']}초, 시도 {r['attempts']}번, 토큰 {r['prompt_tokens']}→{r['completion_tokens']}, 요청 {r['request_id']}")
    print("가짜 답장 판단:", " / ".join(f"{k} {j[k]}" for k in ("mood", "health", "mind", "life", "level", "confidence")))
    print("요약:", j["summary"])
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="CLOVA 답장 분석 확인")
    parser.add_argument("--ping", action="store_true", help="가짜 답장 한 줄로 키와 형식 확인")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if not args.ping:
        parser.print_help()
        raise SystemExit(2)
    raise SystemExit(ping())
