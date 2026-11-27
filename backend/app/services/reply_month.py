"""월간 포트폴리오의 'AI가 정리한 한 달의 변화' (docs/REPLY_ANALYSIS.md 16절).

그 달의 답장 분석(reply_analyses)에서 규칙으로 사실을 센다:
  한 달 흐름(날짜마다 가장 높은 수준·목소리 → 화면의 캘린더), 같은 신호가 나온 날짜, 목소리 흐름, 지난달과 비교, 다음 안부 제안.
그 사실만 CLOVA Studio(HCX-007)에 보내, 2~3문장 정리와 '이번 달 나눈 이야기'(답장을 다섯 갈래로 나눈 것)를 한 번에 받는다
(답장 원문은 보내지 않고, 답장마다 AI가 만든 요약·분류와 센 숫자만).
- 사실은 보고서(monthly_portfolios)에 저장하지 않고 볼 때마다 계산한다. 분석을 끄거나 답장을 지우면 저절로 사라진다.
- CLOVA 정리문·주제 묶음만 reply_analysis_months에 저장한다 (사실이 바뀌면 stale). 분석 끄기·답장 지우기·동의 철회 때 같이 지운다.
- 진단·점수·등급은 쓰지 않는다. 문구는 답장 카드와 같은 표(LEVEL_UI, MOOD_UI)를 쓴다.
"""

import argparse
import hashlib
import json
import logging
import re
import statistics

from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import settings
from ..db import iso, utcnow
from ..models import Recipient, ReplyAnalysis, ReplyAnalysisMonth, SeniorReply, User
from . import reply_llm
from . import reply_analysis as rules
from .conversations import korea_date, month_bounds
from .reply_gpu import AnalysisError
from .replies import parties

log = logging.getLogger("ongi.reply_month")

ENOUGH = 3  # 정리한 답장이 이만큼은 있어야 한 달의 흐름을 말한다
NOTICE = "AI가 답장마다 정리한 내용을 한 달로 모았어요. 진단이 아니니 답장을 함께 읽고 들어 보세요."
FEW_TEXT = f"아직 정리한 답장이 적어 한 달의 흐름을 말하기 어려워요 ({ENOUGH}개부터 정리해요)."
VOICE_WORDS = {"비슷": "평소와 비슷", "처짐": "평소보다 처짐", "기록 중": "평소 목소리 기록 중", "측정 못 함": "재지 못함"}
# 이어진 이야기에서 고르는 다음 안부 (신호 값마다). 진단·지시가 아니라 안부를 묻는 말
STARTERS = {
    "아픔": "아프신 곳이 요즘 어떠신지 여쭤보세요.",
    "넘어짐·다침": "넘어지신 뒤 움직이기 불편한 곳은 없는지 여쭤보세요.",
    "병원·약": "병원 다녀오신 뒤 어떠신지, 약은 잘 챙기시는지 여쭤보세요.",
    "식사·잠 문제": "요즘 식사와 잠은 어떠신지 여쭤보세요.",
    "기타 건강": "몸은 요즘 어떠신지 편하게 여쭤보세요.",
    "외로움": "자주 연락드리고, 함께할 시간을 정해 보세요.",
    "의욕 없음": "요즘 즐거웠던 일이나 해 보고 싶은 일이 있는지 여쭤보세요.",
    "짐이 된다는 말": "부담이 아니라는 마음을 말로 전해 보세요.",
    "죽음·살기 싫다는 말": "직접 전화하거나 찾아뵙고 이야기를 들어 보세요. 걱정되면 자살예방 상담전화(109)와 함께 의논할 수 있어요.",
    "기타 마음": "요즘 마음 쓰이는 일이 있는지 편하게 여쭤보세요.",
    "돈 문제": "생활에 필요한 것이 있는지 조심스럽게 여쭤보세요.",
    "사기 의심": "모르는 연락이나 송금 요청이 있었는지 여쭤보고, 함께 확인해 드리겠다고 말해 보세요.",
    "혼자 해결 못 하는 일": "도움이 필요하던 일이 해결됐는지 여쭤보고 함께 방법을 찾아보세요.",
    "기타 생활": "생활에서 불편한 일이 없는지 여쭤보세요.",
}

SUMMARY_SYSTEM = """너는 자녀에게 부모님이 한 달 동안 남긴 답장의 흐름을 정리해 주는 도우미다. 입력은 답장마다 AI가 정리한 내용(번호, 날짜, 살펴볼 정도, 기분, 확인해 볼 것, 목소리, 요약)과 그것을 센 숫자다.
- 입력에 있는 사실만 쓴다. 없는 일을 짐작하거나 원인을 추측하지 않는다.
- 진단하지 않는다. 병명, 점수, 등급, 진단 같은 말을 쓰지 않는다.
- 부모님은 [부르는 말]로 부른다. 말투는 "~했어요", "~보여요"처럼 부드럽게 쓴다.
[summary] 한 달 동안 무엇이 이어졌고, 달의 처음과 끝이 어떻게 달라졌는지를 2~3문장으로 쓴다. 날짜는 "11월 10일", "중순"처럼 쓴다. 지난달과 비교한 숫자가 있으면 한 번만 짧게 말한다. 숫자를 늘어놓지 않는다. '바로 연락 필요' 답장 중 뒤에서 해결되지 않은 것이 있으면 그 날짜와 일을 꼭 쓰고, 그런 달은 끝이 평온했다고 쓰지 않는다. 끝났다고 쓰는 일은 resolved 목록에도 꼭 넣는다.
[topics] 이번 달 답장을 아래 다섯 갈래로 나눈다. 답장이 없는 갈래는 쓰지 않고, 같은 갈래는 한 번만 쓴다. 답장이 많은 갈래부터 쓴다.
- 건강: 몸, 아픔, 다침, 병원·약, 식사·잠
- 마음·외로움: 외로움, 쓸쓸함, 의욕, 서운함 같은 마음 이야기
- 생활·안전: 돈, 사기 의심 전화, 집 고장처럼 생활에서 생긴 일
- 가족: 자녀·손주·가족 소식과 만남
- 일상: 나들이, 취미, 음식, 날씨 같은 하루 이야기
'확인해 볼 것'에 건강 신호가 있으면 건강, 마음 신호가 있으면 마음·외로움, 생활·안전 신호가 있으면 생활·안전에 넣는다(여럿이면 가장 중요한 하나). 확인해 볼 것이 없는데 '살펴보기'인 답장(말과 목소리가 다른 답장 등)은 마음·외로움에 넣는다. 가족·일상에는 '살펴보기'나 '바로 연락 필요' 답장을 넣지 않는다. 신호가 없어도 앞 답장의 걱정되는 일이 이어지거나 끝난 이야기(예: "이제 괜찮아", "병원 다녀왔어", "돈 안 보냈어")면 그 일의 갈래에 넣는다. 그 밖에 신호가 없으면 가족이나 일상에 넣는다.
- name: 갈래 이름 (위 다섯 가지 글자 그대로)
- status: 그 갈래 이야기가 이번 달 어떻게 흘러갔는지 하나. 이어지는 중(살펴볼 일이 마지막 답장까지 이어짐) / 나아지는 중(살펴볼 일이 뒤 답장에서 나아지고 있지만 끝나지는 않음) / 해결 완료(살펴볼 일이 뒤 답장에서 끝났다고 확인됨) / 평소 이야기(살펴볼 일이 없던 갈래)
- replies: 그 갈래에 넣은 [답장별 정리]의 번호 목록. 1번부터 마지막 번호까지 모든 답장을 꼭 한 갈래에 넣는다(답장 하나는 한 갈래에만). 살펴볼 일이 없는 평범한 답장도 빠뜨리지 말고 가족이나 일상에 넣는다.
- steps: 그 갈래 이야기의 흐름을 보여 주는 답장 1~4개 (날짜 순). 첫 상황과 마지막 상황(특히 '바로 연락 필요'나 해결된 일)은 꼭 넣는다. reply=그 답장의 번호, label=그 답장에서 있었던 일을 2~10자로 짧게 (예: "무릎 통증 시작", "정형외과·약", "계단 오를 만큼", "송금 멈춤")
[resolved] '살펴보기'나 '바로 연락 필요'였던 답장 중, 그 뒤에 온 답장(같은 날 뒤 답장 포함, 살펴볼 정도가 원래보다 낮은 답장)에서 바로 그 일이 끝났거나 위험이 지나갔다고 확인되는 것의 목록. reply=끝난 일의 답장 번호, by=끝났다고 알려 준 뒤 답장 번호. 나아지고 있지만 끝나지 않은 일, 다른 일을 말한 답장, 확실하지 않은 것은 넣지 않는다. 없으면 빈 목록.
출력은 JSON 하나: summary=정리한 2~3문장, topics=갈래 목록, resolved=해결된 답장 목록."""
# 이번 달 나눈 이야기의 갈래 (2026-11-26: 주제를 CLOVA가 자유롭게 정하면 신호마다 갈래가 생겨 너무 잘게 나뉘어 다섯 갈래로 고정)
CATEGORIES = ["건강", "마음·외로움", "생활·안전", "가족", "일상"]
# 갈래의 흐름 상태 (CLOVA가 답장 흐름을 읽고 고르고, _clean_topics가 단계·해결 목록과 맞게 고친다)
STATUSES = ["이어지는 중", "나아지는 중", "해결 완료", "평소 이야기"]
TOPICS_MAX = len(CATEGORIES)
STEPS_MAX = 4
SUMMARY_SCHEMA = {"type": "object", "properties": {
    "summary": {"type": "string"},
    "topics": {"type": "array", "maxItems": TOPICS_MAX, "items": {"type": "object", "properties": {
        "name": {"type": "string", "enum": CATEGORIES},
        "status": {"type": "string", "enum": STATUSES},
        "replies": {"type": "array", "items": {"type": "integer"}},
        "steps": {"type": "array", "maxItems": STEPS_MAX, "items": {"type": "object", "properties": {
            "reply": {"type": "integer"},
            "label": {"type": "string"},
        }, "required": ["reply", "label"]}},
    }, "required": ["name", "status", "replies", "steps"]}},
    "resolved": {"type": "array", "items": {"type": "object", "properties": {
        "reply": {"type": "integer"},
        "by": {"type": "integer"},
    }, "required": ["reply", "by"]}},
}, "required": ["summary", "topics", "resolved"]}
SUMMARY_PARAMS = {**rules.CLOVA_PARAMS, "maxCompletionTokens": 1000}
BANNED = ("진단", "우울증", "치매", "점수", "질환", "장애")
RANK = {level: i for i, level in enumerate(rules.LEVELS)}


def _number(n, count: int) -> int | None:
    n = int(n) if isinstance(n, str) and n.strip().isdigit() else n
    return n if isinstance(n, int) and not isinstance(n, bool) and 1 <= n <= count else None


def _clean_topics(topics, levels: list[str]) -> list[dict]:
    """CLOVA가 나눈 갈래를 고쳐 쓴다 (levels = [답장별 정리] 번호 순서의 수준). 다섯 갈래가 아닌 이름은 버리고,
    같은 갈래가 두 번 오면 답장을 합친다. 번호가 범위 밖이거나 이미 다른 갈래에 든 답장은 뺀다.
    흐름 단계는 그 갈래 답장만, 이름(2~14자)이 이상하거나 금지어가 있으면 뺀다. 상태는 _settle에서 맞춘다.
    답장이 많은 갈래부터 (같으면 CATEGORIES 순서). 쓸 수 있는 갈래가 하나도 없으면 ValueError (seed+1로 한 번 더)"""
    problem = ValueError("한 달 정리의 갈래 묶음을 쓸 수 없어요 (topics)")
    if not isinstance(topics, list):
        raise problem
    count = len(levels)
    merged: dict[str, dict] = {}
    used = set()
    for topic in topics[:TOPICS_MAX * 2]:
        if not isinstance(topic, dict):
            raise problem
        name, status, numbers, steps = topic.get("name"), topic.get("status"), topic.get("replies"), topic.get("steps")
        if not isinstance(name, str) or not isinstance(numbers, list):
            raise problem
        name = name.strip()
        if name not in CATEGORIES:
            continue
        picked = []
        for n in numbers:
            n = _number(n, count)
            if n and n not in used and n not in picked:
                picked.append(n)
        if not picked:
            continue
        used.update(picked)
        group = merged.setdefault(name, {"name": name, "status": status if status in STATUSES else None,
                                         "replies": [], "steps": []})
        group["replies"] = sorted(group["replies"] + picked)
        for step in steps if isinstance(steps, list) else []:
            n = _number(step.get("reply"), count) if isinstance(step, dict) else None
            label = step.get("label").strip() if n and isinstance(step.get("label"), str) else ""
            if (n in picked and 1 <= rules.hangul_len(label) and len(label) <= 14
                    and not any(word in label for word in BANNED) and all(s["reply"] != n for s in group["steps"])):
                group["steps"].append({"reply": n, "label": label})
    if not merged:
        raise problem
    for group in merged.values():
        group["steps"] = sorted(group["steps"], key=lambda s: s["reply"])[:STEPS_MAX]
    return sorted(merged.values(), key=lambda g: (-len(g["replies"]), CATEGORIES.index(g["name"])))


def _settle(topics: list[dict], resolved, levels: list[str], signals: list[set]) -> list[int]:
    """해결된 답장 번호를 고르고 갈래 상태를 그것과 맞춘다 (코드 규칙으로 한 번 더).
    levels·signals = [답장별 정리] 번호 순서의 수준과 신호({(칸, 값)}).
    - 해결: CLOVA가 준 {reply, by} 짝마다, reply가 '살펴보기' 이상이고 by가 그 뒤에 온 **reply보다 낮은 단계**의 답장이어야 한다
      (바로 연락 → 살펴보기·평소, 살펴보기 → 평소). 2026-11-27: 사기 전화 뒤 "돈 안 보냈어" 답장도 사기 이야기라 살펴보기로 나와서,
      '평소와 같아요'만 받던 규칙으로는 바로 연락이 해결 완료가 되지 못했다. 같은 단계(살펴보기 → 살펴보기)는 여전히 받지 않는다.
      갈래는 보지 않는다 ("이제 괜찮아" 같은 답장은 신호가 없어 다른 갈래로 갈 수 있다).
      by 뒤에 같은 신호(칸·값)가 reply와 같거나 더 높은 단계로 다시 나오면 그 일은 끝나지 않은 것이라 받지 않는다.
    - 상태: 살펴볼 답장이 없으면 평소 이야기, 살펴볼 답장이 모두 해결됐으면 해결 완료,
      남았는데 해결 완료라고 하면 나아지는 중, 남았는데 평소 이야기(또는 상태 없음)라고 하면 이어지는 중"""
    count = len(levels)
    fixed = set()
    for pair in resolved if isinstance(resolved, list) else []:
        n = _number(pair.get("reply"), count) if isinstance(pair, dict) else None
        m = _number(pair.get("by"), count) if isinstance(pair, dict) else None
        if not n or not m or levels[n - 1] == "없음" or m <= n or RANK[levels[m - 1]] >= RANK[levels[n - 1]]:
            continue
        reopened = any(RANK[levels[k - 1]] >= RANK[levels[n - 1]] and signals[k - 1] & signals[n - 1]
                       for k in range(m + 1, count + 1))
        if not reopened:
            fixed.add(n)
    for t in topics:
        flagged = [n for n in t["replies"] if levels[n - 1] != "없음"]
        if not flagged:
            t["status"] = "평소 이야기"
        elif all(n in fixed for n in flagged):
            t["status"] = "해결 완료"
        elif t["status"] == "해결 완료":
            t["status"] = "나아지는 중"
        elif t["status"] in (None, "평소 이야기"):
            t["status"] = "이어지는 중"
    return sorted(fixed)


SIGNAL_TOPIC = {"health": "건강", "mind": "마음·외로움", "life": "생활·안전"}
CALM_TOPICS = ("가족", "일상")  # 살펴볼 답장을 두지 않는 갈래 (늘 '평소 이야기')
# CLOVA가 빠뜨린 평범한 답장을 가족에 넣는 말 (답장마다 AI가 쓴 요약에서 찾는다. '딸기'·'아이고' 같은 말은 빼려고 좁게 잡았다)
FAMILY_WORDS = re.compile(r"손주|손자|손녀|아기|애기|아드님|아들|따님|딸(?!기)|며느리|사위|자녀|가족|조카|돌잔치|돌잡이")


def _home_topic(n: int, levels: list[str], signals: list[set], summaries: list[str | None]) -> str:
    """코드가 고르는 갈래: 신호가 있으면 그 신호의 갈래(건강 → 마음·외로움 → 생활·안전 순서로 먼저 있는 것),
    신호 없이 살펴볼 답장(말·목소리 불일치, 가라앉은 기분 3번 연속)은 마음·외로움,
    평범한 답장은 AI 요약에 가족 말(손주·아들·딸 등)이 있으면 가족, 아니면 일상"""
    keys = {key for key, _value in signals[n - 1]}
    name = next((SIGNAL_TOPIC[key] for key in SIGNAL_TOPIC if key in keys), None)
    if name:
        return name
    if levels[n - 1] != "없음":
        return "마음·외로움"
    return "가족" if FAMILY_WORDS.search(summaries[n - 1] or "") else "일상"


def _fill_missing(topics: list[dict], levels: list[str], signals: list[set], summaries: list[str | None]) -> list[dict]:
    """CLOVA가 어느 갈래에도 넣지 않은 답장을 코드로 넣는다 (_home_topic. 2026-11-27, 시연에서 24개 중 10개만 묶이고
    나머지가 모두 일상으로 간 일이 있었다). 가족·일상에 든 살펴볼 답장도 빼서 다시 넣는다 (신호 없는 11/18 말·목소리 불일치가
    일상에 들어가 일상이 '이어지는 중'으로 보였다). 빈 갈래는 지운다. 새로 생긴 갈래는 흐름 단계가 없고 상태는 _settle이 정한다"""
    for t in topics:
        if t["name"] in CALM_TOPICS:
            t["replies"] = [n for n in t["replies"] if levels[n - 1] == "없음"]
            t["steps"] = [s for s in t["steps"] if s["reply"] in t["replies"]]
    topics = [t for t in topics if t["replies"]]
    used = {n for t in topics for n in t["replies"]}
    by_name = {t["name"]: t for t in topics}
    for n in range(1, len(levels) + 1):
        if n in used:
            continue
        name = _home_topic(n, levels, signals, summaries)
        if name not in by_name:
            by_name[name] = {"name": name, "status": None, "replies": [], "steps": []}
            topics.append(by_name[name])
        by_name[name]["replies"] = sorted(by_name[name]["replies"] + [n])
    return sorted(topics, key=lambda g: (-len(g["replies"]), CATEGORIES.index(g["name"])))


def _signal_label(signals: set) -> str:
    """흐름 점 이름을 CLOVA가 주지 않았을 때: 그 답장의 신호 값 (건강 → 마음 → 생활·안전 순)"""
    values = dict(signals)
    return next((values[key] for key in SIGNAL_TOPIC if key in values), "바로 연락 필요")


def _keep_urgent_steps(topics: list[dict], levels: list[str], signals: list[set], fixed: list[int]) -> None:
    """해결되지 않은 '바로 연락 필요' 답장은 그 갈래의 흐름 점에 꼭 넣는다 (2026-11-27, CLOVA가 11/26 넘어짐을 빼고
    앞쪽 무릎 이야기만 고른 일이 있었다). 4개가 넘으면 첫 점과 꼭 넣을 점은 남기고 두 번째 점부터 줄인다"""
    for t in topics:
        must = [n for n in t["replies"] if levels[n - 1] == "바로 연락 필요" and n not in fixed]
        have = {s["reply"] for s in t["steps"]}
        steps = t["steps"] + [{"reply": n, "label": _signal_label(signals[n - 1])} for n in must if n not in have]
        steps.sort(key=lambda s: s["reply"])
        while len(steps) > STEPS_MAX:
            drop = next((i for i in range(1, len(steps)) if steps[i]["reply"] not in must), None)
            if drop is None:
                steps = steps[-STEPS_MAX:]
                break
            del steps[drop]
        t["steps"] = steps


def _urgent_left(levels: list[str], fixed: list[int], dates: list[str]) -> list[str]:
    """해결되지 않은 '바로 연락 필요' 답장의 날짜"""
    return sorted({dates[n - 1] for n in range(1, len(levels) + 1) if levels[n - 1] == "바로 연락 필요" and n not in fixed})


def _urgent_text(days: list[str]) -> str:
    """정리 문장에 빠진 '바로 연락 필요' 날에 붙이는 문장. 화면 표시를 그대로 말한다 (2026-11-27: "…답장이 있었어요"라고 붙였더니
    CLOVA가 '해결됐다'고 쓴 문장 뒤에서 앞뒤가 어긋나 보였다. 코드가 해결로 받지 않은 일이면 화면도 빨강이라 이렇게 말하는 게 맞다)"""
    return f"{', '.join(_day_text(d) for d in days)} 답장은 '바로 연락해 보세요'로 표시돼 있어요. 그날 대화를 꼭 확인해 보세요."


def _check_summary(out, levels: list[str], signals: list[set], dates: list[str] | None = None,
                   summaries: list[str | None] | None = None, strict: bool = False) -> None:
    """정리 문장을 보고, 갈래 묶음·해결 목록은 고친 것으로 바꿔 둔다
    (levels·signals·dates·summaries = [답장별 정리] 번호 순서의 수준·신호·날짜·AI 요약).
    해결되지 않은 '바로 연락 필요' 날짜가 문장에 없으면 strict일 때는 ValueError(seed+1로 한 번 더),
    아니면 그 날의 문장을 끝에 붙인다 (CLOVA가 11/26 넘어짐을 빼고 '평온하게 끝났다'고 쓴 일이 있었다)"""
    text = out.get("summary") if isinstance(out, dict) else None
    if (not isinstance(text, str) or rules.hangul_len(text) < 10 or len(text) > 500
            or any(word in text for word in BANNED)):
        raise ValueError("한 달 정리 문장을 쓸 수 없어요 (summary)")
    out["topics"] = _fill_missing(_clean_topics(out.get("topics"), levels), levels, signals,
                                  summaries or [None] * len(levels))
    out["resolved"] = _settle(out["topics"], out.get("resolved"), levels, signals)
    _keep_urgent_steps(out["topics"], levels, signals, out["resolved"])
    missing = [d for d in _urgent_left(levels, out["resolved"], dates or [])
               if not re.search(rf"(?<!\d){int(d[8:])}일", text)]
    if missing and strict:
        raise ValueError("한 달 정리 문장에 바로 연락이 필요했던 날이 빠졌어요 (summary)")
    if missing:
        out["summary"] = text.rstrip() + " " + _urgent_text(missing)


def _prev_month(month: str) -> str:
    year, mon = map(int, month.split("-"))
    return f"{year - (mon == 1)}-{(mon - 2) % 12 + 1:02d}"


def _day_text(day: str) -> str:
    return f"{int(day[5:7])}월 {int(day[8:10])}일"


def _rows(db: Session, recipient: Recipient, start, end):
    return db.execute(
        select(ReplyAnalysis, SeniorReply).join(SeniorReply, SeniorReply.id == ReplyAnalysis.reply_id)
        .where(ReplyAnalysis.user_id == recipient.user_id, ReplyAnalysis.recipient_id == recipient.id,
               SeniorReply.created_at >= start, SeniorReply.created_at < end)
        .order_by(SeniorReply.created_at, SeniorReply.id)
    ).all()


def _counts(db: Session, recipient: Recipient, start, end, rows) -> dict:
    def count(*conditions) -> int:
        return db.scalar(select(func.count()).select_from(SeniorReply).where(
            SeniorReply.user_id == recipient.user_id, SeniorReply.recipient_id == recipient.id,
            SeniorReply.created_at >= start, SeniorReply.created_at < end, *conditions)) or 0
    done = [a for a, _r in rows if a.status == "done" and a.result]
    return {"replies": count(), "voice": count(SeniorReply.kind == "voice"),
            "check": sum(1 for a in done if a.level != "없음"),
            "urgent": sum(1 for a in done if a.level == "바로 연락 필요"),
            "lengths": [a.reply_chars for a in done if a.reply_chars],
            **_voice_tally([a for a, _r in rows], done)}


# 지난달과 비교의 목소리 줄: 운율 항목마다 '평소보다 처진' 음성 답장 수 (reply_analysis.PROSODY_FEATS의 키)
FEAT_ROWS = {"rate": "말이 느려진 답장", "loudness_db": "목소리가 작아진 답장", "pitch_st": "목소리가 낮아진 답장",
             "pitch_range_st": "높낮이가 단조로워진 답장", "pause_ratio": "자주 멈춘 답장"}


def _voice_tally(analyses, done) -> dict:
    """평소 목소리와 비교한 음성 답장(기록 중·측정 못 함은 빼고)에서 처진 답장, 말·목소리가 다른 답장, 항목별 처짐을 센다"""
    compared = [a for a in analyses if a.kind == "voice" and (a.voice or {}).get("status") == "비교"]
    feats = {key: sum(1 for a in compared if any(item.get("key") == key and item.get("state") == "처짐"
                                                 for item in a.voice.get("items", [])))
             for key in FEAT_ROWS}
    return {"voice_compared": len(compared), "voice_down": sum(1 for a in compared if a.voice.get("voice_down")),
            "mismatch": sum(1 for a in done if a.voice_mismatch), "feats": feats}


def _compare_rows(now: dict, prev: dict) -> list[dict]:
    """지난달과 비교: 답장 줄 4개 + 음성 답장이 있으면 목소리 줄 (처진 답장·말과 목소리가 다른 답장은 늘 보이고,
    운율 항목은 두 달 중 한 번이라도 처진 것만)"""
    def row(group, label, key, unit, sub=None):
        get = (lambda c: c[key][sub]) if sub else (lambda c: c[key])
        return {"group": group, "label": label, "prev": get(prev), "now": get(now), "unit": unit}
    # 답장 수·음성 답장 수 줄은 뺐다 (2026-11-26, 캘린더·원형 그래프와 겹친다)
    rows = [row("답장", "살펴보기 이상", "check", "번"), row("답장", "바로 연락 필요", "urgent", "번")]
    if now["voice_compared"] or prev["voice_compared"]:
        rows += [row("목소리", "평소보다 처진 답장", "voice_down", "번"), row("목소리", "말과 목소리가 다른 답장", "mismatch", "번")]
        rows += [row("목소리", label, "feats", "번", key) for key, label in FEAT_ROWS.items()
                 if now["feats"][key] or prev["feats"][key]]
    return rows


RESOLVED_LABEL = "해결 완료"
PENDING_LABELS = {"queued": "정리 중", "running": "정리 중", "stt_uncertain": "받아쓰기 불확실", "failed": "정리하지 못함"}


def _items(rows) -> list[dict]:
    """답장마다 화면에 쓰는 값 (캘린더·그날 답장·원형 그래프). 정리 전이면 level·summary가 None.
    signals는 해결 판정용 신호 {(칸, 값)} (화면에는 보내지 않는다)"""
    out = []
    for a, r in rows:
        done = a.status == "done" and bool(a.result)
        out.append({"reply_id": r.id, "date": korea_date(r.created_at), "status": a.status,
                    "level": a.level if done else None, "summary": a.result.get("summary") if done else None,
                    "signals": {(key, a.result[key]) for key, _area in rules.SIG_NAMES
                                if a.result.get(key, "없음") != "없음"} if done else set(),
                    "voice": a.kind == "voice", "voice_down": a.kind == "voice" and _voice_state(a.voice) == "처짐",
                    "mismatch": done and bool(a.voice_mismatch)})
    return out


def _label(item: dict, resolved: set[int]) -> str:
    if item["level"] is None:
        return PENDING_LABELS.get(item["status"], "정리 전")
    return RESOLVED_LABEL if item["reply_id"] in resolved else rules.LEVEL_UI[item["level"]][0]


def _levels(items: list[dict], resolved: set[int]) -> list[dict]:
    """이번 달 답장 상태 (원형 그래프): 정리한 답장의 수준별 수 (해결 완료된 답장은 따로) + 정리 전 답장 수"""
    open_ = [i for i in items if i["level"] and i["reply_id"] not in resolved]
    out = [{"key": level, "label": rules.LEVEL_UI[level][0], "count": sum(1 for i in open_ if i["level"] == level)}
           for level in rules.LEVELS]
    out.append({"key": "resolved", "label": RESOLVED_LABEL,
                "count": sum(1 for i in items if i["level"] and i["reply_id"] in resolved)})
    out.append({"key": "pending", "label": "정리 전", "count": sum(1 for i in items if not i["level"])})
    return out


def _voice_state(voice: dict | None) -> str | None:
    if not voice:
        return None
    if voice.get("status") in ("기록 중", "측정 못 함"):
        return voice["status"]
    return "처짐" if voice.get("voice_down") else "비슷"


def _length_text(now: list[int], prev: list[int]) -> str | None:
    """답장 길이 비교 (CLOVA에 보낸 글자 수의 가운데 값). 양쪽 다 2개 이상일 때만"""
    if len(now) < 2 or len(prev) < 2:
        return None
    ratio = statistics.median(now) / max(statistics.median(prev), 1)
    if ratio < 0.7:
        return "지난달보다 답장이 짧아졌어요"
    if ratio > 1.3:
        return "지난달보다 답장이 길어졌어요"
    return "답장 길이는 지난달과 비슷해요"


def _days(items: list[dict], resolved: set[int]) -> list[dict]:
    """캘린더용: 날짜마다 정리한 답장 수, 해결되지 않은 답장 중 가장 높은 수준, 목소리가 처진 답장·말과 목소리가 다른 답장이 있었는지.
    그날 살펴볼 답장이 모두 해결 완료면 resolved (수준은 '없음', 이름은 해결 완료).
    any_resolved: 해결 완료된 답장이 하나라도 있는 날 (✓ 배지. 화면은 남은 답장이 살펴보기여도 해결 완료 색, 바로 연락 필요면 빨강)"""
    days: dict[str, dict] = {}
    for item in items:
        day = days.setdefault(item["date"], {"date": item["date"], "analyzed": 0, "level": None, "label": "",
                                             "resolved": False, "any_resolved": False, "voice_down": False,
                                             "mismatch": False, "_status": set()})
        if item["level"]:
            day["analyzed"] += 1
            level = "없음" if item["reply_id"] in resolved else item["level"]
            day["any_resolved"] = day["any_resolved"] or item["reply_id"] in resolved
            if day["level"] is None or RANK[level] > RANK[day["level"]]:
                day["level"] = level
        else:
            day["_status"].add(item["status"])
        day["voice_down"] = day["voice_down"] or item["voice_down"]
        day["mismatch"] = day["mismatch"] or item["mismatch"]
    for day in days.values():
        status = day.pop("_status")
        day["resolved"] = day["any_resolved"] and day["level"] == "없음"
        day["label"] = (RESOLVED_LABEL if day["resolved"] else rules.LEVEL_UI[day["level"]][0] if day["level"]
                        else "정리 중" if status & {"queued", "running"}
                        else "받아쓰기 불확실" if "stt_uncertain" in status else "정리하지 못함")
    return [days[d] for d in sorted(days)]


def _build(db: Session, recipient: Recipient, month: str | None) -> tuple[dict, str, list[dict]]:
    """화면에 보낼 사실(캘린더·갈래는 _fill이 채운다), CLOVA에 보낼 글(이름을 가린 것), 답장마다의 값(_items, 날짜 순).
    CLOVA 글의 답장 번호는 items 중 정리한 답장(level이 있는 것)의 순서다"""
    month, start, end = month_bounds(month)
    rows = _rows(db, recipient, start, end)
    done = [(a, r) for a, r in rows if a.status == "done" and a.result]

    # 같은 신호가 나온 횟수·날짜: CLOVA에 보내는 사실과 다음 안부 제안에 쓴다 (화면에는 CLOVA의 주제 묶음을 보여 준다)
    groups: dict[tuple[str, str], dict] = {}
    for a, r in done:
        for key, area in rules.SIG_NAMES:
            value = a.result.get(key)
            if not value or value == "없음":
                continue
            group = groups.setdefault((area, value), {"area": area, "value": value, "count": 0, "dates": []})
            group["count"] += 1
            group["dates"].append(korea_date(r.created_at))
    signals = sorted(groups.values(), key=lambda g: (-g["count"], g["dates"][0]))
    starters = list(dict.fromkeys(STARTERS[g["value"]] for g in signals if g["value"] in STARTERS))[:3]

    # 목소리 횟수: CLOVA에 보내는 사실에만 쓴다 (화면의 '목소리 흐름'은 2026-11-26에 뺐다. 목소리는 지난달과 비교의 목소리 줄과 캘린더 🎤)
    voiced = [a for a, _r in rows if a.kind == "voice" and _voice_state(a.voice)]
    voice = {"count": len(voiced), "down": sum(1 for a in voiced if _voice_state(a.voice) == "처짐"),
             "mismatch": sum(1 for a, _r in done if a.voice_mismatch)} if voiced else None

    now = _counts(db, recipient, start, end, rows)
    prev_month = _prev_month(month)
    _m, prev_start, prev_end = month_bounds(prev_month)
    prev = _counts(db, recipient, prev_start, prev_end, _rows(db, recipient, prev_start, prev_end))
    compare = {"prev_month": prev_month, "rows": _compare_rows(now, prev),
               "length_text": _length_text(now["lengths"], prev["lengths"])}

    # CLOVA에 보낼 사실: 답장 원문 없이 답장마다 AI 요약·분류와 센 숫자만. 이름은 가린다
    call = recipient.nickname if reply_llm._is_honorific(recipient.nickname or "") else "부모님"
    lines = [f"[부르는 말] {call}", f"[달] {month[:4]}년 {int(month[5:])}월",
             f"[답장] {now['replies']}개 (음성 {now['voice']}개), AI가 정리한 답장 {len(done)}개",
             "[지난달과 비교] " + " / ".join(f"{row['label']} {row['prev']}{row['unit']} → {row['now']}{row['unit']}"
                                          for row in compare["rows"]) + (f" / {compare['length_text']}" if compare["length_text"] else ""),
             f"[답장별 정리 (날짜 순, [ ] 안이 번호, 1~{len(done)}번)]"]
    for number, (a, r) in enumerate(done, 1):
        found = ", ".join(f"{area} {a.result[key]}" for key, area in rules.SIG_NAMES if a.result.get(key, "없음") != "없음")
        state = _voice_state(a.voice)
        lines.append(f"- [{number}] {_day_text(korea_date(r.created_at))} | {rules.LEVEL_UI[a.level][0]} | {rules.MOOD_UI.get(a.mood, a.mood)}"
                     f" | 확인해 볼 것: {found or '없음'} | 목소리: {VOICE_WORDS[state] if state else '-'}"
                     f"{' (말과 목소리가 다름)' if a.voice_mismatch else ''} | 요약: {a.result.get('summary', '')}")
    lines.append("[이어진 이야기] " + (" / ".join(
        f"{g['area']} {g['value']} {g['count']}번 ({', '.join(_day_text(d) for d in g['dates'])})" for g in signals) or "없음"))
    if voice:
        lines.append(f"[목소리] 음성 답장 {voice['count']}개 중 평소보다 처진 답장 {voice['down']}번, 말과 목소리가 다른 답장 {voice['mismatch']}번")
    user = db.get(User, recipient.user_id)
    names = reply_llm.names_to_hide(user.name if user else None, recipient.child_call_name, recipient.nickname)
    facts = reply_llm.hide_names("\n".join(lines), names)

    trends = {"month": month, "notice": NOTICE, "analyzed": len(done), "enough": len(done) >= ENOUGH,
              "few_text": FEW_TEXT if len(done) < ENOUGH else None,
              "compare": compare, "starters": starters, "summary": None,
              "can_summarize": len(done) >= ENOUGH and bool(reply_llm.api_key())}
    return trends, facts, _items(rows)


def _fingerprint(facts: str) -> str:
    schema = json.dumps(SUMMARY_SCHEMA, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(f"{rules.PROMPT_ID}\n{SUMMARY_SYSTEM}\n{schema}\n{facts}".encode()).hexdigest()


def _fill(trends: dict, items: list[dict], topics: list[dict] | None, resolved_ids: list[int] | None) -> dict:
    """저장한 갈래 묶음·해결 목록(없으면 None)으로 화면 값을 채운다.
    - days: 캘린더 (해결 완료 반영), levels: 원형 그래프, replies: 날짜를 눌렀을 때 그날 답장 (AI 한 줄 요약·갈래)
    - topics: 갈래마다 상태 배지, 흐름 단계(날짜·짧은 이름·수준), 캘린더에서 강조할 날짜.
    해결 목록·갈래는 정리할 때의 답장 ID라서, 그 뒤 지워진 답장은 건너뛴다"""
    resolved = set(resolved_ids or [])
    by_id = {item["reply_id"]: item for item in items}
    topic_of = {reply_id: t["name"] for t in topics or [] for reply_id in t["reply_ids"]}
    trends["days"] = _days(items, resolved)
    trends["levels"] = _levels(items, resolved)
    trends["replies"] = [{"reply_id": i["reply_id"], "date": i["date"], "level": i["level"], "label": _label(i, resolved),
                          "resolved": i["reply_id"] in resolved and bool(i["level"]), "summary": i["summary"],
                          "topic": topic_of.get(i["reply_id"]), "voice": i["voice"], "voice_down": i["voice_down"]}
                         for i in items]
    trends["topics"] = None
    if topics:
        # 이 형식 전에 저장한 정리(상태·흐름 단계 없음)도 화면이 깨지지 않게 (판단 기준이 바뀌어 낡은 것으로 보이고 다시 정리된다)
        trends["topics"] = [{
            "name": t["name"], "status": t.get("status"), "count": len(t["reply_ids"]),
            "dates": sorted({by_id[r]["date"] for r in t["reply_ids"] if r in by_id}),
            "steps": [{"date": by_id[s["reply_id"]]["date"], "label": s["label"], "level": by_id[s["reply_id"]]["level"],
                       "resolved": s["reply_id"] in resolved}
                      for s in t.get("steps", []) if s["reply_id"] in by_id],
        } for t in topics]
    return trends


def month_trends(db: Session, recipient: Recipient, month: str | None) -> dict | None:
    """기능이 켜져 있고 자녀가 이 대상자에 답장 살펴보기를 켰을 때만. 아니면 None (포트폴리오 응답에 칸을 넣지 않는다)"""
    if not settings.reply_analysis_enabled or "child" not in parties(db, recipient.user_id, recipient.id):
        return None
    trends, facts, items = _build(db, recipient, month)
    saved = db.scalar(select(ReplyAnalysisMonth).where(
        ReplyAnalysisMonth.recipient_id == recipient.id, ReplyAnalysisMonth.user_id == recipient.user_id,
        ReplyAnalysisMonth.month == trends["month"],
    ))
    if saved:
        # 판단 기준·JSON 틀이 바뀌면 fingerprint도 달라서 낡은 것으로 보인다 → 화면이 다시 정리한다
        trends["summary"] = {"text": saved.summary, "generated_at": iso(saved.created_at),
                             "stale": saved.fingerprint != _fingerprint(facts)}
    return _fill(trends, items, saved.topics if saved else None, saved.resolved if saved else None)


def summarize(db: Session, recipient: Recipient, month: str | None) -> dict:
    """사실을 CLOVA로 2~3문장 정리하고 주제별로 묶어 저장한다 (자녀가 포트폴리오를 열었을 때 없거나 낡았으면 화면이 부른다)"""
    if not settings.reply_analysis_enabled or "child" not in parties(db, recipient.user_id, recipient.id):
        raise HTTPException(409, "답장 살펴보기가 꺼져 있어요.")
    trends, facts, items = _build(db, recipient, month)
    if not trends["enough"]:
        raise HTTPException(409, FEW_TEXT)
    order = [item for item in items if item["level"]]  # CLOVA 글의 답장 번호 순서 (번호 n = order[n - 1])
    levels = [item["level"] for item in order]
    checks = []  # 첫 검사는 엄하게(바로 연락 날짜가 빠지면 seed+1로 다시), 두 번째는 빠진 날 문장을 붙여서 받는다

    def check(result) -> None:
        checks.append(1)
        _check_summary(result, levels, [item["signals"] for item in order], [item["date"] for item in order],
                       [item["summary"] for item in order], strict=len(checks) == 1)
    try:
        out = reply_llm.complete_json(SUMMARY_SYSTEM, facts, SUMMARY_SCHEMA, SUMMARY_PARAMS, check)
    except AnalysisError as e:
        raise HTTPException(503 if e.retryable else 502, f"한 달 정리를 만들지 못했어요. {e}")
    month = trends["month"]
    row = db.scalar(select(ReplyAnalysisMonth).where(
        ReplyAnalysisMonth.recipient_id == recipient.id, ReplyAnalysisMonth.month == month))
    if row is None:
        try:
            with db.begin_nested():
                row = ReplyAnalysisMonth(user_id=recipient.user_id, recipient_id=recipient.id, month=month,
                                         fingerprint="", summary="", model=out["model"])
                db.add(row)
                db.flush()
        except IntegrityError:
            row = db.scalar(select(ReplyAnalysisMonth).where(
                ReplyAnalysisMonth.recipient_id == recipient.id, ReplyAnalysisMonth.month == month))
            if row is None:
                raise
    row.summary, row.fingerprint = out["json"]["summary"].strip(), _fingerprint(facts)
    # 답장 번호를 답장 ID로 바꿔 저장한다 (번호는 이번에 보낸 글에서만 뜻이 있다)
    rid = lambda n: order[n - 1]["reply_id"]  # noqa: E731
    row.topics = [{"name": t["name"], "status": t["status"], "reply_ids": [rid(n) for n in t["replies"]],
                   "dates": sorted({order[n - 1]["date"] for n in t["replies"]}),
                   "steps": [{"reply_id": rid(s["reply"]), "label": s["label"]} for s in t["steps"]]}
                  for t in out["json"]["topics"]]
    row.resolved = [rid(n) for n in out["json"]["resolved"]]
    row.model, row.created_at = out["model"], utcnow()
    db.commit()
    log.info("한 달 정리 %s #%s (%.1f초, 시도 %s, 갈래 %s개, 해결 %s개, 토큰 %s→%s)", month, recipient.id, out["seconds"],
             out["attempts"], len(row.topics), len(row.resolved), out["prompt_tokens"], out["completion_tokens"])
    trends["summary"] = {"text": row.summary, "generated_at": iso(row.created_at), "stale": False}
    return _fill(trends, items, row.topics, row.resolved)


def delete_months(db: Session, user_id: int, recipient_id: int | None = None, month: str | None = None) -> int:
    """분석 끄기(대상자 전체)·답장 지우기(그 달)·동의 철회(사용자 전체) 때 저장한 정리문을 지운다"""
    query = delete(ReplyAnalysisMonth).where(ReplyAnalysisMonth.user_id == user_id)
    if recipient_id is not None:
        query = query.where(ReplyAnalysisMonth.recipient_id == recipient_id)
    if month is not None:
        query = query.where(ReplyAnalysisMonth.month == month)
    return db.execute(query).rowcount


# ---------------------------------------------------------------- 확인 명령 ----
PING_FACTS = """[부르는 말] 엄마
[달] 2026년 11월
[답장] 3개 (음성 1개), AI가 정리한 답장 3개
[지난달과 비교] 답장 2개 → 3개 / 음성 답장 0개 → 1개 / 살펴보기 이상 0번 → 2번 / 바로 연락 필요 0번 → 0번
[답장별 정리 (날짜 순, [ ] 안이 번호, 1~3번)]
- [1] 11월 3일 | 평소와 같아요 | 밝아 보여요 | 확인해 볼 것: 없음 | 목소리: - | 요약: 경로당에서 점심을 드셨대요.
- [2] 11월 7일 | 살펴보기 | 평온해 보여요 | 확인해 볼 것: 건강 아픔 | 목소리: - | 요약: 무릎이 아파 병원에 다녀오셨대요.
- [3] 11월 10일 | 살펴보기 | 평온해 보여요 | 확인해 볼 것: 건강 아픔 | 목소리: 평소와 비슷 | 요약: 무릎이 아직 아프시대요.
[이어진 이야기] 건강 아픔 2번 (11월 7일, 11월 10일)"""


def ping() -> int:
    """가짜 사실 몇 줄로 한 달 정리의 JSON 틀(정리 문장 + 주제 묶음)을 CLOVA가 받아 주는지 본다 (실제 답장은 보내지 않는다)"""
    print(f"주소 {settings.reply_llm_endpoint} | 키 {'있음' if reply_llm.api_key() else '없음'}")
    if not reply_llm.api_key():
        print("REPLY_LLM_API_KEY 또는 NAVER_API_KEY를 backend/.env에 넣어 주세요.")
        return 1
    try:
        out = reply_llm.complete_json(SUMMARY_SYSTEM, PING_FACTS, SUMMARY_SCHEMA, SUMMARY_PARAMS,
                                      lambda result: _check_summary(result, ["없음", "살펴보기", "살펴보기"],
                                                                    [set(), {("health", "아픔")}, {("health", "아픔")}]))
    except AnalysisError as e:
        print(f"실패: {e} ({'나중에 다시 하면 될 수 있음' if e.retryable else '설정이나 JSON 틀을 고쳐야 함'})")
        return 1
    print(f"성공: {out['seconds']}초, 시도 {out['attempts']}번, 토큰 {out['prompt_tokens']}→{out['completion_tokens']}")
    print("정리:", out["json"]["summary"])
    for topic in out["json"]["topics"]:
        steps = " → ".join(f"{s['reply']}번 {s['label']}" for s in topic["steps"])
        print(f"갈래: {topic['name']} · {topic['status']} (답장 {topic['replies']}) {steps}")
    print("해결 완료로 본 답장:", out["json"]["resolved"] or "없음")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="CLOVA 한 달 정리 확인")
    parser.add_argument("--ping", action="store_true", help="가짜 사실 몇 줄로 키와 JSON 틀(주제 묶음) 확인")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if not args.ping:
        parser.print_help()
        raise SystemExit(2)
    raise SystemExit(ping())
