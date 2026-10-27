"""한 줄 메모 -> 15~20초 영상 대본. HyperCLOVA X로 만들고 JSON 파싱·길이·금칙어를 검증한다."""

import json
import re
import time
import unicodedata
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import httpx

from ..config import log, settings
from .korean import has_batchim

# 상황 설명은 분위기와 목적만 알려 준다. "날씨를 챙겨 드린다"처럼 쓰면 메모에 없는 날씨를 지어내기 때문에
# 정보가 필요한 상황은 '메모에 적힌'으로 범위를 묶는다
TEMPLATES = {
    "greeting": ("안부", "평소처럼 안부를 전합니다."),
    "birthday": ("생일", "부모님 생신을 축하합니다."),
    "holiday": ("명절", "명절 인사를 전합니다."),
    "weather": ("날씨", "메모에 적힌 날씨 이야기를 전하며 건강을 챙겨 드립니다."),
    "hospital": ("병원 일정", "메모에 적힌 병원·약 일정을 날짜와 시간 그대로 정확히 전합니다."),
}

# 대본 길이 = 생성 시간과 GPU 비용. 공백을 뺀 글자 수 기준, 노인 대상 말하기 속도는 초당 약 5.5자
HARD_LIMIT_CHARS = (8, 120)
CHARS_PER_SECOND = 5.5

# 후보 대본의 분위기: (라벨, 설명, 목표 글자 수, 말투별 모양 예시)
# "다정하게/밝게" 같은 형용사만 주면 후보끼리 비슷해져서, 무엇을 덧붙이는지와 문장 모양으로 정의한다.
# 예시는 메모 '주말에 갈게'로 쓴 것이라 내용을 베끼지 않고 모양만 참고한다
STYLES = {
    "plain": (
        "담백하게",
        "메모 내용만 1~2문장으로 전하세요. 인사, 걱정, 당부, '사랑해' 같은 애정 표현은 넣지 마세요.",
        # 메모 내용만 쓰므로 짧은 메모('주말에 갈게')는 30자를 못 채운다. 30자일 때 시도 70번 중 32번이 짧다고 다시 쓰였고,
        # 늘리라는 피드백이 메모에 없는 말을 지어내게 했다
        (15, 45),
        {"존댓말": "엄마, 이번 주말에 갈게요. 그때 봬요.", "반말": "엄마, 이번 주말에 갈게. 그때 봐."},
    ),
    "warm": (
        "다정하게",
        "메모 내용을 전한 뒤 부모님 안부를 묻는 질문 하나, 몸 챙기시라는 당부 하나를 덧붙이고 마음을 전하며 끝내세요.",
        (60, 85),
        {
            "존댓말": "엄마, 이번 주말에 갈게요. 요즘 아픈 데 없이 잘 지내고 계시죠? 아무리 바쁘셔도 식사 거르지 마시고 밤에는 일찍 푹 주무세요. 늘 고맙고, 정말 많이 보고 싶어요.",
            "반말": "엄마, 이번 주말에 갈게. 요즘 아픈 데 없이 잘 지내고 있지? 아무리 바빠도 밥 거르지 말고 밤에는 일찍 푹 자. 엄마한테 늘 고맙고, 정말 많이 보고 싶어.",
        },
    ),
    "bright": (
        "밝게",
        "호칭을 반갑게 부르며 시작하고, 짧은 문장 여러 개와 느낌표로 들뜬 기분을 전하세요. 걱정이나 당부 대신 기대감과 응원을 덧붙이세요.",
        (45, 65),
        {
            "존댓말": "엄마! 저 이번 주말에 가요! 오랜만에 엄마 얼굴 볼 생각에 벌써부터 너무 신나요. 그때까지 매일 웃으면서 지내요!",
            "반말": "엄마! 나 이번 주말에 간다! 오랜만에 엄마 얼굴 볼 생각에 벌써부터 너무 신나. 그때까지 매일 웃으면서 지내!",
        },
    ),
}
DEFAULT_STYLE = "warm"

# 자녀 목소리로 돈·개인정보를 요구하는 영상은 보이스피싱 수법과 같아서 만들지 않는다
# '돈'이라는 말 없이 금액만 대는 요청('십만 원만 보내 주세요')도 막는다. 돈과 동사 사이에는 조사와 '미리·급하게' 같은
# 말만 허용해서 '돈 걱정 말고 반찬 보내 줘', '오만 원짜리 케이크 보내 드릴게요', '용돈 줘서 고마워'는 통과한다.
# 이미 받은 돈에 대한 인사('용돈 보내줘서 고마워', '보내 주신 거 받았어')도 통과한다. AI가 '줘서'를 '보내줘서'로 바꿔 써서 막혔었다.
# AI는 메모의 돈 요청을 말만 바꿔 옮겨서(실험 14번 중 11번) 실제로 나온 표현('용돈 좀 미리 보내줄 수', '급전이 필요',
# '생활비 좀 부탁할게', '좀 보태줘')을 기준으로 잡았다. '조금만 도와줄 수 있을까'처럼 돈이란 말과 떨어진 요청은 못 잡는다
_MONEY_NOUN = r"돈|급전|현금|생활비|병원비|수술비|합의금|등록금|보증금|월세|[\d,일이삼사오육칠팔구십백천만억몇]\s?원(?!짜리|어치)"
_MONEY_BETWEEN = (
    r"(?:[\s만씩좀을를이가은는도정쯤큼라]|미리|빨리|얼른|당장|바로|먼저|조금|급하게|급히|급한데|급해서|급하니까|그런데"
    r"|혹시|꼭|지금|오늘|내일)"
)
_MONEY_VERB = (
    r"(?:보내|부쳐|붙여|빌려|꿔|쏴|넣어|보태)(?!\s?(?:줘서|주셔서|준|줬|주신|주셨))"
    r"|필요(?!\s?없)|부탁|줘(?!서)|주세요|주실|줄\s?수|줄래|주면|주라"
)
_MONEY = rf"({_MONEY_NOUN}){_MONEY_BETWEEN}{{0,12}}({_MONEY_VERB})"
_BANNED = [
    (r"송금|입금|이체|계좌|통장 ?번호|" + _MONEY, "돈이나 계좌 관련 요청"),
    (r"비밀 ?번호|인증 ?번호|보안 ?카드|OTP|카드 ?번호|주민 ?(등록)? ?번호|신분증", "개인정보·인증 정보 요청"),
    (r"대출|상품권|기프트 ?카드|문화상품권", "금융·상품권 관련 요청"),
    (
        r"(앱|어플)[을를좀하나\s]{0,5}(깔|설치|다운)|(링크|주소)[를을로에좀\s]{0,4}(눌러|클릭|접속|들어가)|원격",
        "앱 설치·링크 클릭 요청",
    ),
    (r"씨발|시발|ㅅㅂ|병신|ㅂㅅ|개새|좆|존나|지랄|꺼져", "욕설"),
]

SYSTEM_PROMPT = """당신은 바쁜 자녀를 대신해 부모님께 보낼 '영상 편지' 대본을 다듬는 작가입니다.
이 대본은 자녀의 목소리와 얼굴로 만든 AI 영상에서 그대로 읽힙니다. 자녀가 부모님께 직접 말하는 문장으로 쓰세요.

[규칙]
1. 주어진 호칭으로 부르며 시작하세요. (예: "엄마,")
2. 말투: '말투'에 적힌 반말 또는 존댓말을 모든 문장에서 지키세요. '자녀 말투 예시'가 있으면 어미와 자주 쓰는 표현도 따라 하세요.
3. 분량과 분위기: '분량'에 적힌 글자 수(공백 제외)를 지키고 '분위기'에 적힌 대로 쓰세요. '모양 예시'는 문장 모양만 참고하고, 내용은 메모를 따르세요.
4. 메모에 담긴 내용만 전하세요. 메모에 없는 날씨, 일정, 건강 상태, 사건, 약속(예: 사 갈게, 저녁에 봐)을 지어내지 마세요. 덧붙여도 되는 건 감정·안부·응원뿐입니다.
   '상황'은 분위기와 목적만 알려 주는 것입니다. 날씨 상황이어도 메모에 날씨 이야기가 없으면 날씨를 쓰지 마세요.
   메모에 있는 요일·날짜·시간은 그대로 쓰세요. '오늘', '내일'로 바꾸지 마세요.
5. "먼저 먹어", "먼저 자" 같은 말은 부모님께 그렇게 하시라고 권하는 말입니다.
6. 줄임말, 신조어, 외래어, 이모티콘, ㅋㅋ·ㅠㅠ 같은 자모는 쉬운 우리말로 바꾸세요.
7. 숫자는 소리 나는 대로 한글로 쓰세요. (예: 2시 -> 두 시, 100% -> 백 퍼센트)
8. 돈, 계좌, 송금, 인증번호, 비밀번호, 앱 설치, 링크 클릭 같은 요청은 절대 넣지 마세요.

[출력 형식]
다른 말 없이 JSON 한 줄만 출력하세요: {"script": "대본"}"""

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


# 프롬프트로 금지해도 모델이 날씨·요일·시각을 지어내서 (테스트에서 날씨 템플릿 3/3, 병원 템플릿 3/3) 코드로 대조한다
_WEATHER = [
    r"(?<![가-힣])비(?=\s?(가|도|는|를|오|와|온|올|내리|소식|예보|많이|조금|쏟))",
    r"(?<![가-힣])눈(?=\s?(이\s?(오|와|온|올|내리|많이)|오|와|온|올|내리|소식|예보))",
    r"맑",
    r"흐[리린려렸]",
    r"추[워웠운우]|춥|추위",  # '추우니까'
    r"쌀쌀",
    r"더[워웠운우]|덥|더위",  # '더우니까' (메모에서 못 읽어 대본의 '더운데'를 지어낸 날씨로 잡았다)
    r"선선",
    r"기온",
    r"날씨",
    r"미세\s?먼지",
    r"황사",
    r"장마",
    r"태풍",
    r"일교차",
    r"환절기",
    r"구름",
    r"날이\s?((많이|좀|꽤|너무|많이들)\s?)?(차|추|더|좋|풀)",
]
_HOUR_WORDS = {"한": 1, "두": 2, "세": 3, "네": 4, "다섯": 5, "여섯": 6, "일곱": 7, "여덟": 8, "아홉": 9, "열": 10, "열한": 11, "열두": 12}
# '언니네 시댁'(4시), '모두 시원'(2시)처럼 앞 단어의 끝 글자를 시각으로 읽지 않도록 앞에 한글이 붙어 있으면 건너뛴다.
# '오후세시'처럼 때를 나타내는 말에 붙여 쓴 것만 시각으로 본다
_HOUR_WORD = "열두|열한|열|아홉|여덟|일곱|여섯|다섯|네|세|두|한"
_HOUR = re.compile(
    r"(?:(?<![가-힣])|(?<=오전|오후|아침|저녁|새벽|점심)|(?<=[밤낮]))"
    rf"({_HOUR_WORD})\s*시(?![간작장청험계])"
)
# 숫자는 '내일3시'처럼 붙여 써도 시각이 분명하므로 한글로 바꾸지 않고 따로 읽는다. 15시 -> 3시
_HOUR_DIGITS = re.compile(r"(?<!\d)(\d{1,2})\s*시(?![간작장청험계])")


def _hours(text: str) -> set[int]:
    words = {_HOUR_WORDS[h] for h in _HOUR.findall(text)}
    return words | {int(h) % 12 or 12 for h in _HOUR_DIGITS.findall(text)}


# 병원 일정은 날짜·분이 바뀌면 안 된다. 메모는 숫자로 적힌 것만 읽고('이 일 끝나면'을 2일로 읽지 않도록),
# 대본은 한글 숫자(삼 일, 삼십 분)까지 넓게 읽는다. 대본 쪽은 넓게 읽어도 빠짐 검사가 느슨해질 뿐 잘못된 경고는 안 나온다
_SINO = r"(?:[이삼사오]?십)?[일이삼사오육칠팔구]?"
_SINO_DIGITS = {"일": 1, "이": 2, "삼": 3, "사": 4, "오": 5, "육": 6, "칠": 7, "팔": 8, "구": 9}
_MEMO_DATE = {
    "월": re.compile(r"(?<!\d)(\d{1,2})\s*월"),
    # '1일 3회', '3일 동안'은 날짜가 아니라 기간이다
    "일": re.compile(r"(?<!\d)(\d{1,2})\s*일(?!\s*(?:동안|간|치|째|뒤|후|전|마다|\d+\s*[회번]))"),
    "분": re.compile(r"(?<!\d)(\d{1,2})\s*분"),
}
_SCRIPT_DATE = {
    "월": re.compile(rf"(\d{{1,2}}|{_SINO}|유|시)\s?월(?!요)"),
    "일": re.compile(rf"(\d{{1,2}}|{_SINO})\s?일(?![월요])"),
    "분": re.compile(rf"(\d{{1,2}}|{_SINO})\s?분"),
}
# 시각 바로 앞에 붙은 말만 본다. '아침 잘 챙겨 드세요'의 아침은 끼니라서
_MERIDIEM = re.compile(rf"(오전|오후|아침|저녁|새벽|밤|낮|점심)\s*(?:\d{{1,2}}|{_HOUR_WORD})\s*시(?![간작장청험계])")
_PM_WORDS = {"오후", "저녁", "밤", "낮", "점심"}


def _number(word: str) -> int:
    """3, 삼, 삼십오, 유(월), 시(월) -> 정수. 빈 문자열은 0."""
    if word.isdigit():
        return int(word)
    if word in ("유", "시"):
        return 6 if word == "유" else 10
    tens, sep, ones = word.rpartition("십")
    return (_SINO_DIGITS.get(tens, 1) * 10 if sep else 0) + _SINO_DIGITS.get(ones, 0)


def _date_parts(text: str, from_memo: bool) -> list[str]:
    patterns = _MEMO_DATE if from_memo else _SCRIPT_DATE
    parts = [f"{n}{unit}" for unit, p in patterns.items() for n in map(_number, p.findall(text)) if n]
    if re.search(r"\d\s*시\s*반" if from_memo else r"시\s?반", text):
        parts.append("30분")
    return list(dict.fromkeys(parts))


def _meridiem(word: str) -> str:
    return "오후" if word in _PM_WORDS else "오전"


def unsupported_facts(script: str, memo: str) -> list[str]:
    """메모에 없는데 대본에 들어간 날씨·요일·시각."""
    found = []
    if any(re.search(p, script) for p in _WEATHER) and not any(re.search(p, memo) for p in _WEATHER):
        found.append("날씨")
    memo_days = set(re.findall(r"([월화수목금토일])(?:요일|욜)", memo))
    for day in dict.fromkeys(re.findall(r"([월화수목금토일])요일", script)):
        if day not in memo_days:
            found.append(f"{day}요일")
    memo_hours = _hours(memo)
    for hour in sorted(_hours(script) - memo_hours):
        found.append(f"{hour}시")
    return found


def missing_facts(script: str, memo: str) -> list[str]:
    """메모에 있는데 대본에서 빠지거나 바뀐 날짜·요일·시각. 오늘이 목요일이면 '목요일'을 '오늘'로 바꾸는 일이 실제로 있었다.
    3일 -> 5일, 오후 -> 오전처럼 바뀐 것도 메모의 값이 빠진 것으로 잡힌다."""
    found = []
    script_days = set(re.findall(r"([월화수목금토일])요일", script))
    for day in dict.fromkeys(re.findall(r"([월화수목금토일])(?:요일|욜)", memo)):
        if day not in script_days:
            found.append(f"{day}요일")
    for hour in sorted(_hours(memo) - _hours(script)):
        found.append(f"{hour}시")
    script_parts = set(_date_parts(script, from_memo=False))
    found += [p for p in _date_parts(memo, from_memo=True) if p not in script_parts]
    script_meridiems = {_meridiem(w) for w in _MERIDIEM.findall(script)}
    found += [w for w in dict.fromkeys(_MERIDIEM.findall(memo)) if _meridiem(w) not in script_meridiems]
    return found


def fact_warnings(script: str, memo: str, replies: Sequence[str] = ()) -> list[str]:
    """화면에 보여 줄 경고 문구. 대본을 만들 때 넣은 부모님 답글에 나온 내용은 지어낸 것으로 보지 않는다"""
    warnings = []
    if added := unsupported_facts(script, " ".join((memo, *replies))):
        warnings.append(f"메모{'나 답글' if replies else ''}에 없던 내용이 들어갔어요: {', '.join(added)}")
    if missing := missing_facts(script, memo):
        warnings.append(f"메모에 있던 내용이 빠졌어요: {', '.join(missing)}")
    return warnings


# 말투. 후보 3개를 따로 요청하기 때문에 "말투를 통일하라"는 규칙은 소용이 없어서(테스트에서 3/3 섞임)
# 코드로 먼저 정해 세 요청에 똑같이 넣는다
_POLITE_END = re.compile(r"(요|니다|세요|십시오|습니까)$")
_CASUAL_FINAL = set("어아야지자게래네니냐해줘봐와겨려쳐써까대데라다걸돼워셔")


def _sentence_levels(text: str) -> list[str]:
    body = re.sub(r"^\s*[^\s,!]+[,!]\s*", "", text)  # 맨 앞 호칭("엄마,")은 빼고 본다
    levels = []
    for sentence in re.split(r"[.!?~\n]+", body):
        words = re.findall(r"[가-힣]+", sentence)
        if not words:
            continue
        last = words[-1]
        if _POLITE_END.search(last):
            levels.append("존댓말")
        elif last[-1] in _CASUAL_FINAL:
            levels.append("반말")
    return levels


def speech_level(tone: str, memo: str, preferred: str = "") -> str:
    """부모님 정보에서 고른 말투 > 말투 예시 > 메모 어미 순으로 정한다.
    메모는 부모님께 하는 말이 아니라 앱에 쓰는 메모라서(할머니께는 존댓말인데 메모는 반말 등) 가장 마지막에 본다."""
    if preferred in ("반말", "존댓말"):
        return preferred
    for text in (tone, memo):
        # 메모는 띄어쓰기로만 이어 쓰는 경우가 많아서 단어 끝마다 본다
        words = re.findall(r"[가-힣]+", text)
        if any(_POLITE_END.search(w) for w in words):
            return "존댓말"
        if any(w[-1] in _CASUAL_FINAL for w in words):
            return "반말"
    return "존댓말"


def speech_mismatch(script: str, level: str) -> bool:
    other = "반말" if level == "존댓말" else "존댓말"
    return other in _sentence_levels(script)


# ㅋㅋ·ㅠㅠ 같은 자모. 'ᄒᄒ', 'ᅲ'는 ㅎ·ㅠ와 모양만 같은 조합용 자모(U+1100~)라서 따로 넣었다 (실험 응답에서 5번 나왔다).
# 조합용 자모로 쪼개진(NFD) 글자까지 지우지 않도록 지우기 전에 NFC로 합친다
_JAMO = r"[ㄱ-ㅎㅏ-ㅣᄀ-ᇿꥠ-꥿ힰ-퟿]+"


def _extract_script(raw: str) -> str | None:
    """모델이 JSON 앞뒤에 설명을 붙여도 {...} 부분만 꺼내서 읽는다."""
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
        script = data.get("script") if isinstance(data, dict) else None
    except json.JSONDecodeError:
        # {"script : "..."}처럼 따옴표가 빠진 JSON도 실제로 나와서 값만 꺼내 본다
        loose = re.search(r'script"?\s*:\s*"(.+?)"\s*\}', match.group(0), re.DOTALL)
        script = loose.group(1) if loose else None
    if not isinstance(script, str):
        return None
    # 규칙으로 막아도 이모티콘(😊)과 자모가 나와서 지운다. TTS가 읽거나 이상하게 끊는다
    script = re.sub(r"[\U0001F000-\U0001FAFF☀-➿️‍]|" + _JAMO, "", unicodedata.normalize("NFC", script))
    # 줄바꿈이 있는 말투 예시를 따라 여러 줄로 쓰는 경우가 있어서 한 줄로 만든다
    script = re.sub(r"\s+", " ", script).strip()
    return script or None


def _length_feedback(script: str, target: tuple[int, int]) -> list[str]:
    # 모델은 목표보다 짧게 쓰는 경향이 있어서 아래쪽 허용 폭을 좁게 둔다
    n, (lo, hi) = char_count(script), target
    if n < lo * 0.8:
        return [f"너무 짧습니다(공백 제외 {n}자). {lo}~{hi}자로 늘려 주세요."]
    if n > hi * 1.15:
        return [f"너무 깁니다(공백 제외 {n}자). {lo}~{hi}자로 줄여 주세요."]
    return []


def _one_line(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _conversation_block(replies: Sequence[str], previous_script: str) -> str:
    """부모님 답글이 있을 때만 붙이는 '최근 대화'. 답글이 없으면 프롬프트가 예전과 똑같다.
    줄바꿈이 섞이면 다른 항목처럼 보여서(말투 예시에서 대본이 여러 줄로 나왔다) 한 줄씩 따옴표로 넣는다."""
    if not replies:
        return ""
    lines = [f'- 직전 편지(자녀): "{_one_line(previous_script)}"'] if previous_script else []
    lines += [f'- 부모님 답글: "{_one_line(r)}"' for r in replies]
    return (
        "최근 대화 (오래된 순):\n" + "\n".join(lines) + "\n"
        "대화 규칙: 호칭 다음에 부모님 답글에 한 문장으로 짧게 반응하고 나서 메모를 전하세요. "
        "답글에 있는 내용에만 반응하고 답글을 길게 되풀이하거나 답글에 없는 내용을 지어내지 마세요. "
        "직전 편지는 무엇에 대한 답글인지 알려 주는 것이니 그 내용을 다시 쓰지 마세요. "
        "분위기가 '메모 내용만' 전하라고 하면 답글에 반응하지 마세요.\n"
    )


def _user_prompt(
    memo: str,
    template: str,
    nickname: str,
    relation: str,
    child_name: str,
    tone: str,
    style: str,
    level: str,
    replies: Sequence[str] = (),
    previous_script: str = "",
) -> str:
    # 오늘 날짜는 넣지 않는다. 넣었더니 오늘이 목요일일 때 메모의 '목요일'을 '오늘'로 바꾸고(6/6),
    # 생일 메모에 '오늘 생신'처럼 날짜를 넘겨짚었다
    label, desc = TEMPLATES.get(template, TEMPLATES["greeting"])
    _, style_desc, (lo, hi), examples = STYLES[style]
    return (
        f"호칭: {nickname}\n"
        f"관계: {relation}\n"
        f"자녀 이름: {child_name}\n"
        f"말투: {level}\n"
        f"자녀 말투 예시: {tone.strip() or '(없음)'}\n"
        f"상황: {label} - {desc}\n"
        f"분위기: {style_desc}\n"
        f"모양 예시 (메모 '주말에 갈게'일 때): {examples[level]}\n"
        f"분량: 공백 빼고 {lo}~{hi}자\n"
        + _conversation_block(replies, previous_script)
        + f"메모: {memo}"
    )


# 후보 하나를 만드는 전체 시간 한도(재요청·재시도 포함). 대본 생성은 '메시지 만들기' 요청 안에서 돌기 때문에
# 오래 걸리면 프록시나 브라우저가 먼저 끊고, 그사이 서버는 메시지를 저장해서 다시 누르면 중복이 생긴다
TIME_LIMIT_SECONDS = 15.0
_MIN_CALL_SECONDS = 2.0  # 남은 시간이 이보다 적으면 새로 부르지 않는다


def _call_hcx(messages: list[dict], temperature: float, deadline: float) -> str:
    """연결이 끊기거나(실제로 WinError 10054가 가끔 난다) 429/5xx면 잠깐 쉬었다가 다시 부른다.
    deadline(time.monotonic 기준)까지 남은 시간만큼만 기다리고, 모자라면 TimeoutError를 낸다."""
    for attempt in range(3):
        remaining = deadline - time.monotonic()
        if remaining < _MIN_CALL_SECONDS:
            raise TimeoutError(f"대본 생성 시간 한도({TIME_LIMIT_SECONDS:.0f}초)를 넘었어요")
        try:
            resp = httpx.post(
                settings.hcx_endpoint,
                headers={"Authorization": f"Bearer {settings.naver_api_key}", "Content-Type": "application/json"},
                # 호출 한도는 입력 토큰 + maxTokens로 센다. 대본은 공백 포함 최대 약 170자(약 110토큰)라 200이면 충분하다
                json={"messages": messages, "temperature": temperature, "topP": 0.8, "maxTokens": 200},
                timeout=min(30.0, remaining),
            )
            resp.raise_for_status()
            return resp.json()["result"]["message"]["content"]
        except httpx.HTTPError as e:
            status = e.response.status_code if isinstance(e, httpx.HTTPStatusError) else None
            retryable = status is None or status == 429 or status >= 500
            wait = 2 * (attempt + 1)
            if not retryable or attempt == 2 or deadline - time.monotonic() < wait + _MIN_CALL_SECONDS:
                raise
            log.info("HyperCLOVA X 재시도 (%s): %s", attempt + 1, e)
            time.sleep(wait)
    raise AssertionError("unreachable")


_CLOSINGS = {  # (존댓말, 반말). 약속("또 연락드릴게요")은 자녀가 안 한 말이라 넣지 않는다
    "greeting": ("늘 건강 챙기세요.", "늘 건강 챙겨."),
    "birthday": ("늘 건강하세요.", "늘 건강해."),
    "holiday": ("명절 잘 보내세요.", "명절 잘 보내."),
    "weather": ("따뜻하게 챙겨 입으시고, 건강 조심하세요.", "따뜻하게 챙겨 입고, 건강 조심해."),
    "hospital": ("병원 다녀오시면 꼭 알려 주세요.", "병원 다녀오면 꼭 알려 줘."),
}


def fallback(memo: str, template: str, nickname: str, level: str = "존댓말") -> str:
    polite, casual = _CLOSINGS.get(template, _CLOSINGS["greeting"])
    closing = casual if level == "반말" else polite
    if template == "birthday" and "축하" not in memo:
        closing = ("생일 정말 축하해. " if level == "반말" else "생신 정말 축하드려요. ") + closing
    body = re.sub(_JAMO, "", unicodedata.normalize("NFC", memo)).strip().rstrip(".~")
    if body and body[-1] not in "?!":
        body += "."
    return " ".join(p for p in (f"{nickname},", body, closing) if p)


def generate_candidates(
    memo: str,
    template: str,
    nickname: str,
    relation: str,
    child_name: str,
    tone: str = "",
    level: str | None = None,
    replies: Sequence[str] = (),
    previous_script: str = "",
) -> list[dict]:
    """분위기가 다른 후보를 동시에 만든다. 같은 문장(규칙 기반 대체 등)은 하나로 합친다.
    replies: 직전 편지 이후 부모님 답글(오래된 순). 있으면 대본이 답글에 짧게 반응한다."""
    level = level or speech_level(tone, memo)
    with ThreadPoolExecutor(max_workers=len(STYLES)) as pool:
        futures = {
            style: pool.submit(
                generate, memo, template, nickname, relation, child_name, tone, style, level,
                replies=replies, previous_script=previous_script,
            )
            for style in STYLES
        }
    candidates, seen = [], set()
    for style, future in futures.items():
        r = future.result()
        if r.script in seen:
            continue
        seen.add(r.script)
        llm = r.source == "llm"
        candidates.append(
            {"style": style if llm else "basic", "label": STYLES[style][0] if llm else "기본", "script": r.script, "source": r.source}
        )
    return candidates


def generate(
    memo: str,
    template: str,
    nickname: str,
    relation: str,
    child_name: str,
    tone: str = "",
    style: str = DEFAULT_STYLE,
    level: str | None = None,
    replies: Sequence[str] = (),
    previous_script: str = "",
) -> ScriptResult:
    level = level or speech_level(tone, memo)
    if not settings.naver_api_key:
        script = fallback(memo, template, nickname, level)
        return ScriptResult(script, "fallback", validate(script))

    target = STYLES[style][2]
    prompt = _user_prompt(memo, template, nickname, relation, child_name, tone, style, level, replies, previous_script)
    messages = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}]
    # 답글에 나온 날씨·요일·시각에 반응한 건 지어낸 게 아니다. 빠짐 검사는 그대로 메모만 본다
    source = " ".join((memo, *replies))
    where = "메모나 답글" if replies else "메모"
    # (문제 수, 대본) 중 문제가 가장 적은 것을 남긴다
    best: tuple[int, str] | None = None
    deadline = time.monotonic() + TIME_LIMIT_SECONDS
    for attempt in range(3):
        try:
            raw = _call_hcx(messages, temperature=0.5 if attempt == 0 else 0.3, deadline=deadline)
        except Exception as e:  # 네트워크·인증 오류, 시간 초과는 지금까지 나온 가장 나은 대본이나 규칙 기반으로 대체
            log.warning("HyperCLOVA X 호출 실패 (%s번째 시도): %s", attempt + 1, e)
            break
        script = _extract_script(raw)
        if script is None:
            log.warning("HyperCLOVA X 응답 파싱 실패: %r", raw[:200])
            feedback = ['반드시 {"script": "..."} 형식의 JSON 한 줄만 출력하세요.']
        else:
            feedback = validate(script) + _length_feedback(script, target)
            facts = unsupported_facts(script, source)
            if facts:
                feedback.append(
                    f"{where}에 없는 내용({', '.join(facts)})을 넣었어요. {where}에 없는 날씨·요일·시간은 빼고, {where}에 있는 것만 전해 주세요."
                )
            missing = missing_facts(script, memo)
            if missing:
                feedback.append(
                    f"메모의 {', '.join(missing)}을(를) 빠뜨리거나 바꿨어요. '오늘'·'내일'로 바꾸지 말고 메모에 적힌 대로 써 주세요."
                )
            if speech_mismatch(script, level):
                feedback.append(f"말투가 섞였어요. 모든 문장을 {level}로 맞춰 주세요.")
            if not feedback:
                return ScriptResult(script, "llm")
            # 길이·말투 문제보다 사실이 틀린 게 더 나쁘므로 틀린 항목 수만큼 더 무겁게 친다
            score = len(feedback) + len(facts) + len(missing)
            if best is None or score < best[0]:
                best = (score, script)
        messages += [
            {"role": "assistant", "content": raw},
            {"role": "user", "content": "앞의 결과에 문제가 있어요: " + " ".join(feedback) + " 규칙을 지켜 다시 써 주세요."},
        ]

    if best is not None:
        return ScriptResult(best[1], "llm", validate(best[1]))
    script = fallback(memo, template, nickname, level)
    return ScriptResult(script, "fallback", validate(script))


def subject(nickname: str) -> str:
    """알림 문구용: 엄마가 / 아버님이"""
    return nickname + ("이" if has_batchim(nickname) else "가")
