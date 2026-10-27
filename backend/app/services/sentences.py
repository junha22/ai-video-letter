"""목소리 등록용 대본 30개: 감정 12개, 차분한 문장 8개, 발음 10개. 각 약 10초."""

import json
import random
from pathlib import Path

SENTENCES = json.loads(
    (Path(__file__).resolve().parents[3] / "shared" / "voice-sentences.json").read_text(encoding="utf-8")
)

_LEGACY_GUIDES = {
    "calm": ("calm", "차분하게", "일정한 음량으로 차분하게 읽어 주세요. 평소 말투와 편안한 속도를 유지해 주세요."),
    "statement": ("calm", "평소 말하듯", "가족에게 일상을 전하듯 편안하게 읽어 주세요. 문장 끝까지 자연스럽게 이어 주세요."),
    "question": ("emotion", "궁금한 마음으로", "상대방의 안부를 묻듯 읽어 주세요. 질문하는 부분의 높낮이를 자연스럽게 살려 주세요."),
    "exclamation": ("emotion", "밝게, 감정을 담아서", "문장에 어울리는 감정을 목소리에 담아 주세요. 소리를 크게 지르기보다 자연스럽게 표현해 주세요."),
}


def guidance(sentence: dict) -> dict:
    """예전 녹음 대본에도 안내를 제공하되 저장된 대본이나 녹음 인덱스를 바꾸지 않는다."""
    category, hint, guide = _LEGACY_GUIDES.get(sentence["kind"], _LEGACY_GUIDES["statement"])
    return {
        "category": sentence.get("category", category),
        "hint": sentence.get("hint", hint),
        "guide": sentence.get("guide", guide),
        "focus": list(sentence.get("focus", [])),
    }


def assign() -> list[dict]:
    """카테고리 안에서 섞고, 참조 음성 후보부터 세 유형을 번갈아 배정한다.

    완료 여부는 문장 개수가 아닌 실제 누적 녹음 시간(기본 135초)으로 판단한다.
    목표 시간까지 읽는 앞부분에서도 감정·차분한 문장·발음이 고르게 등장한다.
    """
    categories = ("calm", "emotion", "pronunciation")
    pools = {
        category: random.sample(pool, len(pool))
        for category in categories
        if (pool := [sentence for sentence in SENTENCES if sentence["category"] == category])
    }
    out = []
    while any(pools.values()):
        for category in categories:
            if pools.get(category):
                sentence = pools[category].pop()
                out.append({**sentence, "focus": list(sentence["focus"])})
    return out
