"""한 줄 메모 -> 15~20초 영상 대본. HyperCLOVA X로 만들고 JSON 파싱·길이·금칙어를 검증한다."""

import json
import re
from dataclasses import dataclass, field
from datetime import datetime

import httpx

from ..config import log, settings
from .korean import has_batchim

TEMPLATES = {
    "greeting": ("안부", "평소 안부를 전합니다."),
    "birthday": ("생일", "부모님 생신을 축하합니다."),
    "holiday": ("명절", "명절 인사를 전합니다."),
    "weather": ("날씨", "날씨에 맞춰 건강과 옷차림을 챙겨 드립니다."),
    "hospital": ("병원 일정", "병원 예약이나 약 복용 일정을 알려 드립니다."),
}

# 대본 길이 = 생성 시간과 GPU 비용. 공백을 뺀 글자 수 기준, 노인 대상 말하기 속도는 초당 약 5.5자
TARGET_CHARS = (60, 90)
HARD_LIMIT_CHARS = (8, 120)
CHARS_PER_SECOND = 5.5

# 자녀 목소리로 돈·개인정보를 요구하는 영상은 보이스피싱 수법과 같아서 만들지 않는다
_BANNED = [
    (r"송금|입금|이체|계좌|통장 ?번호|돈 ?(좀|을|를)? ?(보내|부쳐|빌려)", "돈이나 계좌 관련 요청"),
    (r"비밀 ?번호|인증 ?번호|보안 ?카드|OTP|카드 ?번호|주민 ?(등록)? ?번호|신분증", "개인정보·인증 정보 요청"),
    (r"대출|상품권|기프트 ?카드|문화상품권", "금융·상품권 관련 요청"),
    (r"앱 ?(을|를)? ?(깔|설치)|링크 ?(를|을)? ?눌러|원격", "앱 설치·링크 클릭 요청"),
    (r"씨발|시발|ㅅㅂ|병신|ㅂㅅ|개새|좆|존나|지랄|꺼져", "욕설"),
]

SYSTEM_PROMPT = """당신은 바쁜 자녀를 대신해 부모님께 보낼 '영상 편지' 대본을 다듬는 작가입니다.
이 대본은 자녀의 목소리와 얼굴로 만든 AI 영상에서 그대로 읽힙니다. 자녀가 부모님께 직접 말하는 문장으로 쓰세요.

[규칙]
1. 주어진 호칭으로 부르며 시작하세요. (예: "엄마,")
2. 말투: '자녀 말투 예시'가 있으면 그 말투(반말·존댓말, 어미, 자주 쓰는 표현)를 따라 하세요. 없으면 다정한 해요체로 쓰세요.
3. 분량: 소리 내어 읽었을 때 15~20초. 공백을 빼고 60~90자, 2~4문장.
4. 메모에 담긴 내용만 전하세요. 메모에 없는 날씨, 일정, 건강 상태, 사건을 지어내지 마세요. 짧은 인사나 안부 한마디는 덧붙여도 됩니다.
5. "먼저 먹어", "먼저 자" 같은 말은 부모님께 그렇게 하시라고 권하는 말입니다.
6. 줄임말, 신조어, 외래어, 이모티콘, ㅋㅋ·ㅠㅠ 같은 자모는 쉬운 우리말로 바꾸세요.
7. 숫자는 소리 나는 대로 한글로 쓰세요. (예: 2시 -> 두 시, 100% -> 백 퍼센트)
8. 돈, 계좌, 송금, 인증번호, 비밀번호, 앱 설치, 링크 클릭 같은 요청은 절대 넣지 마세요.

[출력 형식]
다른 말 없이 JSON 한 줄만 출력하세요: {"script": "대본"}"""

_WEEKDAYS = "월화수목금토일"


@dataclass
class ScriptResult:
    script: str
    source: str  # llm | fallback
    problems: list[str] = field(default_factory=list)


def char_count(script: str) -> int:
    return len(re.sub(r"\s", "", script))


def estimate_seconds(script: str) -> float:
    return round(char_count(script) / CHARS_PER_SECOND, 1)


def validate(script: str) -> list[str]:
    """돌려준 문제가 하나라도 있으면 영상을 만들 수 없다."""
    problems = []
    n = char_count(script)
    if n < HARD_LIMIT_CHARS[0]:
        problems.append("대본이 너무 짧아요.")
    if n > HARD_LIMIT_CHARS[1]:
        problems.append(f"대본이 너무 길어요. 공백 빼고 {HARD_LIMIT_CHARS[1]}자(약 20초) 안으로 줄여 주세요.")
    for pattern, label in _BANNED:
        if re.search(pattern, script, re.IGNORECASE):
            problems.append(f"넣을 수 없는 내용이 있어요: {label}")
    return problems


def _extract_script(raw: str) -> str | None:
    """모델이 JSON 앞뒤에 설명을 붙여도 {...} 부분만 꺼내서 읽는다."""
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    script = data.get("script") if isinstance(data, dict) else None
    return script.strip() if isinstance(script, str) and script.strip() else None


def _length_feedback(script: str) -> list[str]:
    n = char_count(script)
    if n < TARGET_CHARS[0] - 15:
        return [f"너무 짧습니다(공백 제외 {n}자). 60~90자로 늘려 주세요."]
    if n > TARGET_CHARS[1] + 15:
        return [f"너무 깁니다(공백 제외 {n}자). 60~90자로 줄여 주세요."]
    return []


def _user_prompt(memo: str, template: str, nickname: str, relation: str, child_name: str, tone: str) -> str:
    label, desc = TEMPLATES.get(template, TEMPLATES["greeting"])
    now = datetime.now()
    return (
        f"호칭: {nickname}\n"
        f"관계: {relation}\n"
        f"자녀 이름: {child_name}\n"
        f"자녀 말투 예시: {tone.strip() or '(없음)'}\n"
        f"상황: {label} - {desc}\n"
        f"오늘: {now.year}년 {now.month}월 {now.day}일 ({_WEEKDAYS[now.weekday()]})\n"
        f"메모: {memo}"
    )


def _call_hcx(messages: list[dict], temperature: float) -> str:
    resp = httpx.post(
        settings.hcx_endpoint,
        headers={"Authorization": f"Bearer {settings.naver_api_key}", "Content-Type": "application/json"},
        json={"messages": messages, "temperature": temperature, "topP": 0.8, "maxTokens": 300},
        timeout=30.0,
    )
    resp.raise_for_status()
    return resp.json()["result"]["message"]["content"]


def fallback(memo: str, template: str, nickname: str) -> str:
    closing = {
        "greeting": "늘 건강 챙기시고, 또 연락드릴게요.",
        "birthday": "생신 정말 축하드려요. 늘 건강하세요.",
        "holiday": "명절 잘 보내시고, 곧 찾아뵐게요.",
        "weather": "따뜻하게 챙겨 입으시고, 건강 조심하세요.",
        "hospital": "병원 다녀오시면 꼭 알려 주세요.",
    }.get(template, "늘 건강 챙기세요.")
    body = re.sub(r"[ㄱ-ㅎㅏ-ㅣ]+", "", memo).strip().rstrip(".!?~")
    body = f"{body}." if body else ""
    return " ".join(p for p in (f"{nickname},", body, closing) if p)


def generate(memo: str, template: str, nickname: str, relation: str, child_name: str, tone: str = "") -> ScriptResult:
    if not settings.naver_api_key:
        script = fallback(memo, template, nickname)
        return ScriptResult(script, "fallback", validate(script))

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": _user_prompt(memo, template, nickname, relation, child_name, tone)},
    ]
    best: str | None = None
    for attempt in range(2):
        try:
            raw = _call_hcx(messages, temperature=0.5 if attempt == 0 else 0.3)
        except Exception as e:  # 네트워크·인증 오류는 규칙 기반으로 대체
            log.warning("HyperCLOVA X 호출 실패: %s", e)
            break
        script = _extract_script(raw)
        if script is None:
            log.warning("HyperCLOVA X 응답 파싱 실패: %r", raw[:200])
            feedback = ['반드시 {"script": "..."} 형식의 JSON 한 줄만 출력하세요.']
        else:
            best = script
            feedback = validate(script) + _length_feedback(script)
            if not feedback:
                return ScriptResult(script, "llm")
        messages += [
            {"role": "assistant", "content": raw},
            {"role": "user", "content": "앞의 결과에 문제가 있어요: " + " ".join(feedback) + " 규칙을 지켜 다시 써 주세요."},
        ]

    if best is not None:
        return ScriptResult(best, "llm", validate(best))
    script = fallback(memo, template, nickname)
    return ScriptResult(script, "fallback", validate(script))


def subject(nickname: str) -> str:
    """알림 문구용: 엄마가 / 아버님이"""
    return nickname + ("이" if has_batchim(nickname) else "가")
