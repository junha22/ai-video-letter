"""한국어 보조 함수: 조사 선택, TTS용 숫자 읽기, 자막 나누기."""

import re

_SINO = "영일이삼사오육칠팔구"
_NATIVE_ONES = ["", "한", "두", "세", "네", "다섯", "여섯", "일곱", "여덟", "아홉"]
_NATIVE_TENS = ["", "열", "스물", "서른", "마흔", "쉰", "예순", "일흔", "여든", "아흔"]
# 고유어 수사로 읽는 단위
_NATIVE_COUNTERS = "시간|시|살|개|명|마리|잔|그릇|군데|가지"


def has_batchim(word: str) -> bool:
    if not word:
        return False
    ch = word[-1]
    if "가" <= ch <= "힣":
        return (ord(ch) - 0xAC00) % 28 != 0
    return ch in "0136781lmnLMN"  # 숫자·영문 끝소리 대략 처리


def josa(word: str, with_batchim: str, without: str) -> str:
    return word + (with_batchim if has_batchim(word) else without)


def sino(n: int) -> str:
    if n == 0:
        return "영"
    out = []
    for unit_value, unit in ((100_000_000, "억"), (10_000, "만")):
        if n >= unit_value:
            head, n = divmod(n, unit_value)
            out.append(("" if head == 1 and unit == "만" else sino(head)) + unit)
    for value, unit in ((1000, "천"), (100, "백"), (10, "십")):
        digit, n = divmod(n, value)
        if digit:
            out.append(("" if digit == 1 else _SINO[digit]) + unit)
    if n:
        out.append(_SINO[n])
    return "".join(out)


def native(n: int) -> str:
    """1~99를 고유어로. 단위 앞에서는 스물 -> 스무."""
    tens, ones = divmod(n, 10)
    if tens == 2 and ones == 0:
        return "스무"
    return _NATIVE_TENS[tens] + _NATIVE_ONES[ones]


def numbers_to_hangul(text: str) -> str:
    def counter(m: re.Match) -> str:
        n, unit = int(m.group(1)), m.group(2)
        return (native(n) if 1 <= n <= 99 else sino(n)) + " " + unit

    def month(m: re.Match) -> str:
        n = int(m.group(1))
        return {6: "유", 10: "시"}.get(n, sino(n)) + "월"

    def decimal(m: re.Match) -> str:
        whole, frac = m.group(1), m.group(2)
        return sino(int(whole)) + " 점 " + "".join(_SINO[int(d)] for d in frac)

    text = re.sub(r"(\d{1,3}(?:,\d{3})+)", lambda m: m.group(1).replace(",", ""), text)
    text = re.sub(r"(\d+)\s*월", month, text)
    text = re.sub(rf"(\d+)\s*({_NATIVE_COUNTERS})", counter, text)
    text = re.sub(r"(\d+)\s*%", lambda m: sino(int(m.group(1))) + " 퍼센트", text)
    text = re.sub(r"(\d+)\.(\d+)", decimal, text)
    text = re.sub(r"\d+", lambda m: sino(int(m.group(0))), text)
    return text


def split_sentences(text: str) -> list[str]:
    parts = re.findall(r"[^.!?~。]+[.!?~。]*", text.strip())
    return [p.strip() for p in parts if p.strip()]


def make_captions(script: str, duration: float, tail: float = 0.4) -> list[dict]:
    """대본을 문장 단위로 나누고, 글자 수 비율로 시간을 배분한다."""
    sentences = split_sentences(script) or [script]
    weights = [max(len(s.replace(" ", "")), 1) for s in sentences]
    total = sum(weights)
    speech = max(duration - tail, 0.5)
    captions, t = [], 0.0
    for sentence, w in zip(sentences, weights):
        span = speech * w / total
        captions.append({"start": round(t, 2), "end": round(t + span, 2), "text": sentence})
        t += span
    captions[-1]["end"] = round(duration, 2)
    return captions
