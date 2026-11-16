"""월간 포트폴리오의 'AI가 정리한 한 달의 변화' (docs/REPLY_ANALYSIS.md 16절).

그 달의 답장 분석(reply_analyses)에서 규칙으로 사실을 센다:
  한 달 흐름(답장마다 수준·기분·목소리), 이어진 이야기(같은 신호와 날짜·인용), 목소리 흐름, 지난달과 비교, 다음 안부 제안.
그 사실만 CLOVA Studio(HCX-007)에 보내 2~3문장으로 정리한다 (답장 원문은 보내지 않고, 답장마다 AI가 만든 요약·분류와 센 숫자만).
- 사실은 보고서(monthly_portfolios)에 저장하지 않고 볼 때마다 계산한다. 분석을 끄거나 답장을 지우면 저절로 사라진다.
- CLOVA 정리문만 reply_analysis_months에 저장한다 (사실이 바뀌면 stale). 분석 끄기·답장 지우기·동의 철회 때 같이 지운다.
- 진단·점수·등급은 쓰지 않는다. 문구는 답장 카드와 같은 표(LEVEL_UI, MOOD_UI)를 쓴다.
"""

import hashlib
import logging
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

SUMMARY_SYSTEM = """너는 자녀에게 부모님이 한 달 동안 남긴 답장의 흐름을 정리해 주는 도우미다. 입력은 답장마다 AI가 정리한 내용(날짜, 살펴볼 정도, 기분, 확인해 볼 것, 목소리, 요약)과 그것을 센 숫자다.
- 입력에 있는 사실만 쓴다. 없는 일을 짐작하거나 원인을 추측하지 않는다.
- 진단하지 않는다. 병명, 점수, 등급, 진단 같은 말을 쓰지 않는다.
- 한 달 동안 무엇이 이어졌고, 달의 처음과 끝이 어떻게 달라졌는지를 2~3문장으로 쓴다. 날짜는 "11월 10일", "중순"처럼 쓴다.
- 부모님은 [부르는 말]로 부른다. 말투는 "~했어요", "~보여요"처럼 부드럽게 쓴다.
- 지난달과 비교한 숫자가 있으면 한 번만 짧게 말한다. 숫자를 늘어놓지 않는다.
- 출력은 JSON 하나: summary=정리한 2~3문장."""
SUMMARY_SCHEMA = {"type": "object", "properties": {"summary": {"type": "string"}}, "required": ["summary"]}
SUMMARY_PARAMS = {**rules.CLOVA_PARAMS, "maxCompletionTokens": 400}
BANNED = ("진단", "우울증", "치매", "점수", "질환", "장애")


def _check_summary(out) -> None:
    text = out.get("summary") if isinstance(out, dict) else None
    if (not isinstance(text, str) or rules.hangul_len(text) < 10 or len(text) > 500
            or any(word in text for word in BANNED)):
        raise ValueError("한 달 정리 문장을 쓸 수 없어요 (summary)")


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
            "lengths": [a.reply_chars for a in done if a.reply_chars]}


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


def _build(db: Session, recipient: Recipient, month: str | None) -> tuple[dict, str]:
    """화면에 보낼 사실과, CLOVA에 보낼 글(이름을 가린 것)"""
    month, start, end = month_bounds(month)
    rows = _rows(db, recipient, start, end)
    done = [(a, r) for a, r in rows if a.status == "done" and a.result]

    timeline = []
    for a, r in rows:
        item = {"reply_id": r.id, "date": korea_date(r.created_at), "kind": a.kind, "status": a.status, "level": None,
                "label": {"stt_uncertain": "받아쓰기 불확실", "failed": "정리하지 못함"}.get(a.status, "정리 중"),
                "mood_text": None, "voice": None, "mismatch": False}
        if a.status == "done" and a.result:
            item.update(level=a.level, label=rules.LEVEL_UI[a.level][0], mood_text=rules.MOOD_UI.get(a.mood, a.mood),
                        mismatch=bool(a.voice_mismatch))
        if a.kind == "voice":
            state = _voice_state(a.voice)
            item["voice"] = VOICE_WORDS[state] if state else None
        timeline.append(item)

    groups: dict[tuple[str, str], dict] = {}
    for a, r in done:
        for key, area in rules.SIG_NAMES:
            value = a.result.get(key)
            if not value or value == "없음":
                continue
            group = groups.setdefault((area, value), {"area": area, "value": value, "count": 0, "dates": [], "evidence": []})
            group["count"] += 1
            group["dates"].append(korea_date(r.created_at))
            for quote in a.result.get("evidence", [])[:1]:
                if len(group["evidence"]) < 2 and quote not in group["evidence"]:
                    group["evidence"].append(quote)
    signals = sorted(groups.values(), key=lambda g: (-g["count"], g["dates"][0]))
    starters = list(dict.fromkeys(STARTERS[g["value"]] for g in signals if g["value"] in STARTERS))[:3]

    points = [{"date": korea_date(r.created_at), "state": VOICE_WORDS[s]}
              for a, r in rows if a.kind == "voice" and (s := _voice_state(a.voice))]
    voice = {"points": points,
             "down": sum(1 for a, _r in rows if _voice_state(a.voice) == "처짐"),
             "mismatch": sum(1 for a, _r in done if a.voice_mismatch)} if points else None

    now = _counts(db, recipient, start, end, rows)
    prev_month = _prev_month(month)
    _m, prev_start, prev_end = month_bounds(prev_month)
    prev = _counts(db, recipient, prev_start, prev_end, _rows(db, recipient, prev_start, prev_end))
    compare = {"prev_month": prev_month,
               "rows": [{"label": "답장", "prev": prev["replies"], "now": now["replies"], "unit": "개"},
                        {"label": "음성 답장", "prev": prev["voice"], "now": now["voice"], "unit": "개"},
                        {"label": "살펴보기 이상", "prev": prev["check"], "now": now["check"], "unit": "번"},
                        {"label": "바로 연락 필요", "prev": prev["urgent"], "now": now["urgent"], "unit": "번"}],
               "length_text": _length_text(now["lengths"], prev["lengths"])}

    # CLOVA에 보낼 사실: 답장 원문 없이 답장마다 AI 요약·분류와 센 숫자만. 이름은 가린다
    call = recipient.nickname if reply_llm._is_honorific(recipient.nickname or "") else "부모님"
    lines = [f"[부르는 말] {call}", f"[달] {month[:4]}년 {int(month[5:])}월",
             f"[답장] {now['replies']}개 (음성 {now['voice']}개), AI가 정리한 답장 {len(done)}개",
             "[지난달과 비교] " + " / ".join(f"{row['label']} {row['prev']}{row['unit']} → {row['now']}{row['unit']}"
                                          for row in compare["rows"]) + (f" / {compare['length_text']}" if compare["length_text"] else ""),
             "[답장별 정리 (날짜 순)]"]
    for a, r in done:
        found = ", ".join(f"{area} {a.result[key]}" for key, area in rules.SIG_NAMES if a.result.get(key, "없음") != "없음")
        state = _voice_state(a.voice)
        lines.append(f"- {_day_text(korea_date(r.created_at))} | {rules.LEVEL_UI[a.level][0]} | {rules.MOOD_UI.get(a.mood, a.mood)}"
                     f" | 확인해 볼 것: {found or '없음'} | 목소리: {VOICE_WORDS[state] if state else '-'}"
                     f"{' (말과 목소리가 다름)' if a.voice_mismatch else ''} | 요약: {a.result.get('summary', '')}")
    lines.append("[이어진 이야기] " + (" / ".join(
        f"{g['area']} {g['value']} {g['count']}번 ({', '.join(_day_text(d) for d in g['dates'])})" for g in signals) or "없음"))
    if voice:
        lines.append(f"[목소리] 음성 답장 {len(points)}개 중 평소보다 처진 답장 {voice['down']}번, 말과 목소리가 다른 답장 {voice['mismatch']}번")
    user = db.get(User, recipient.user_id)
    names = reply_llm.names_to_hide(user.name if user else None, recipient.child_call_name, recipient.nickname)
    facts = reply_llm.hide_names("\n".join(lines), names)

    trends = {"month": month, "notice": NOTICE, "analyzed": len(done), "enough": len(done) >= ENOUGH,
              "few_text": FEW_TEXT if len(done) < ENOUGH else None, "timeline": timeline, "signals": signals,
              "voice": voice, "compare": compare, "starters": starters, "summary": None,
              "can_summarize": len(done) >= ENOUGH and bool(reply_llm.api_key())}
    return trends, facts


def _fingerprint(facts: str) -> str:
    return hashlib.sha256(f"{rules.PROMPT_ID}\n{SUMMARY_SYSTEM}\n{facts}".encode()).hexdigest()


def month_trends(db: Session, recipient: Recipient, month: str | None) -> dict | None:
    """기능이 켜져 있고 자녀가 이 대상자에 답장 살펴보기를 켰을 때만. 아니면 None (포트폴리오 응답에 칸을 넣지 않는다)"""
    if not settings.reply_analysis_enabled or "child" not in parties(db, recipient.user_id, recipient.id):
        return None
    trends, facts = _build(db, recipient, month)
    saved = db.scalar(select(ReplyAnalysisMonth).where(
        ReplyAnalysisMonth.recipient_id == recipient.id, ReplyAnalysisMonth.user_id == recipient.user_id,
        ReplyAnalysisMonth.month == trends["month"],
    ))
    if saved:
        trends["summary"] = {"text": saved.summary, "generated_at": iso(saved.created_at),
                             "stale": saved.fingerprint != _fingerprint(facts)}
    return trends


def summarize(db: Session, recipient: Recipient, month: str | None) -> dict:
    """사실을 CLOVA로 2~3문장 정리해 저장한다 (자녀가 포트폴리오를 열었을 때 없거나 낡았으면 화면이 부른다)"""
    if not settings.reply_analysis_enabled or "child" not in parties(db, recipient.user_id, recipient.id):
        raise HTTPException(409, "답장 살펴보기가 꺼져 있어요.")
    trends, facts = _build(db, recipient, month)
    if not trends["enough"]:
        raise HTTPException(409, FEW_TEXT)
    try:
        out = reply_llm.complete_json(SUMMARY_SYSTEM, facts, SUMMARY_SCHEMA, SUMMARY_PARAMS, _check_summary)
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
    row.model, row.created_at = out["model"], utcnow()
    db.commit()
    log.info("한 달 정리 %s #%s (%.1f초, 시도 %s, 토큰 %s→%s)", month, recipient.id, out["seconds"], out["attempts"],
             out["prompt_tokens"], out["completion_tokens"])
    trends["summary"] = {"text": row.summary, "generated_at": iso(row.created_at), "stale": False}
    return trends


def delete_months(db: Session, user_id: int, recipient_id: int | None = None, month: str | None = None) -> int:
    """분석 끄기(대상자 전체)·답장 지우기(그 달)·동의 철회(사용자 전체) 때 저장한 정리문을 지운다"""
    query = delete(ReplyAnalysisMonth).where(ReplyAnalysisMonth.user_id == user_id)
    if recipient_id is not None:
        query = query.where(ReplyAnalysisMonth.recipient_id == recipient_id)
    if month is not None:
        query = query.where(ReplyAnalysisMonth.month == month)
    return db.execute(query).rowcount
