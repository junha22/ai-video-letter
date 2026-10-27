"""목소리 등록용 대본 25개. 각 대본은 자연스러운 말투로 약 10초를 목표로 한다."""

import json
import random
from pathlib import Path

SENTENCES = json.loads(
    (Path(__file__).resolve().parents[3] / "shared" / "voice-sentences.json").read_text(encoding="utf-8")
)


def assign() -> list[dict]:
    """전체 대본을 섞되 참조 음성 후보인 차분한 대본부터 시작한다.

    완료 여부는 문장 개수가 아닌 실제 누적 녹음 시간(기본 90초)으로 판단한다.
    """
    out = random.sample(SENTENCES, len(SENTENCES))
    first_calm = next(i for i, sentence in enumerate(out) if sentence["kind"] == "calm")
    out[0], out[first_calm] = out[first_calm], out[0]
    return [dict(sentence) for sentence in out]
