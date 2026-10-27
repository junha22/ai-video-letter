"""Recipient conversations, Korea calendar boundaries, and evidence-only monthly reports."""

import base64
import calendar
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import and_, case, func, or_, select, text, union_all, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..db import iso, utcnow
from ..models import Message, MonthlyPortfolio, ParentProfile, Recipient, SeniorReply, User

KOREA = timezone(timedelta(hours=9), "Asia/Seoul")
WATCHABLE = ("approved", "sent", "viewed")
PROFILE_FIELDS = ("nickname", "relation", "phone", "child_call_name", "speech_level", "tone_examples")


def korea_date(value: datetime | None = None) -> str:
    value = value or utcnow()
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(KOREA).date().isoformat()


def day_bounds(value: str | None = None) -> tuple[str, datetime, datetime]:
    value = value or korea_date()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise HTTPException(422, "날짜는 YYYY-MM-DD 형식이어야 해요.")
    try:
        parsed = date.fromisoformat(value)
        start = datetime(parsed.year, parsed.month, parsed.day, tzinfo=KOREA).astimezone(timezone.utc).replace(tzinfo=None)
        end = start + timedelta(days=1)
    except (ValueError, OverflowError):
        raise HTTPException(422, "올바른 날짜를 선택해 주세요.")
    if value > korea_date():
        raise HTTPException(422, "오늘 이후의 대화는 아직 없어요.")
    return value, start, end


def month_bounds(value: str | None = None) -> tuple[str, datetime, datetime]:
    value = value or korea_date()[:7]
    if not re.fullmatch(r"\d{4}-\d{2}", value):
        raise HTTPException(422, "월은 YYYY-MM 형식이어야 해요.")
    try:
        year, month = map(int, value.split("-"))
        start = datetime(year, month, 1, tzinfo=KOREA)
        end = datetime(year + (month == 12), month % 12 + 1, 1, tzinfo=KOREA)
        start = start.astimezone(timezone.utc).replace(tzinfo=None)
        end = end.astimezone(timezone.utc).replace(tzinfo=None)
    except (ValueError, OverflowError):
        raise HTTPException(422, "올바른 월을 선택해 주세요.")
    if value > korea_date()[:7]:
        raise HTTPException(422, "오늘 이후의 월은 선택할 수 없어요.")
    return value, start, end


def ensure_primary(db: Session, user: User) -> Recipient | None:
    """Idempotent migration; never renumber legacy profiles, messages or share links."""
    profile = user.parent
    if not profile:
        return None
    recipient = db.scalar(select(Recipient).where(Recipient.legacy_parent_id == profile.id))
    if not recipient:
        try:
            with db.begin_nested():
                recipient = Recipient(
                    user_id=user.id, legacy_parent_id=profile.id,
                    **{key: getattr(profile, key) or "" for key in PROFILE_FIELDS},
                )
                db.add(recipient)
                db.flush()
        except IntegrityError:
            recipient = db.scalar(select(Recipient).where(Recipient.legacy_parent_id == profile.id))
            if recipient is None:
                raise
    db.execute(
        update(Message).where(Message.user_id == user.id, Message.parent_id == profile.id, Message.recipient_id.is_(None))
        .values(recipient_id=recipient.id)
    )
    return recipient


def backfill_recipient_data(db: Session) -> None:
    for user in db.scalars(select(User).join(ParentProfile, ParentProfile.user_id == User.id)).all():
        ensure_primary(db, user)
    db.commit()


def owned_recipient(db: Session, user: User, recipient_id: int) -> Recipient:
    ensure_primary(db, user)
    recipient = db.get(Recipient, recipient_id)
    if not recipient or recipient.user_id != user.id:
        raise HTTPException(404, "대화 대상자를 찾을 수 없어요.")
    return recipient


def lock_owner(db: Session, user_id: int) -> None:
    """Serialize public writes/report generation with consent withdrawal."""
    if db.bind.dialect.name == "sqlite":
        # SQLite ignores FOR UPDATE. A harmless write obtains its transaction
        # write lock before checking the token and holds it until commit/rollback.
        db.execute(update(User).where(User.id == user_id).values(id=User.id))
    else:
        db.execute(select(User.id).where(User.id == user_id).with_for_update()).scalar_one()


def video_time(message: Message) -> datetime:
    return message.approved_at or message.created_at


def _day_sql(db: Session, column):
    if db.bind.dialect.name == "postgresql":
        return func.to_char(column + text("INTERVAL '9 hours'"), "YYYY-MM-DD")
    # SQLite rounds fractional seconds to milliseconds; truncate before conversion
    # so 14:59:59.999999 UTC stays on the correct Korea calendar day.
    return func.date(func.substr(column, 1, 19), "+9 hours")


def recipient_summaries(db: Session, recipients: list[Recipient]) -> dict[int, dict]:
    """Three aggregate queries for the whole inbox, without loading its history."""
    if not recipients:
        return {}
    recipient_ids = [recipient.id for recipient in recipients]
    owner_id = recipients[0].user_id
    timestamp = func.coalesce(Message.approved_at, Message.created_at)
    today = korea_date()
    stats = {recipient_id: {"video_count": 0, "reply_count": 0, "today_video_count": 0,
                            "today_reply_count": 0, "last_activity_at": None, "last_preview": ""}
             for recipient_id in recipient_ids}
    videos = db.execute(select(
        Message.recipient_id, func.count(),
        func.sum(case((_day_sql(db, timestamp) == today, 1), else_=0)),
    ).where(Message.user_id == owner_id, Message.recipient_id.in_(recipient_ids), Message.status != "deleted")
        .group_by(Message.recipient_id)).all()
    for recipient_id, count, today_count in videos:
        stats[recipient_id].update(video_count=count, today_video_count=int(today_count or 0))
    replies = db.execute(select(
        SeniorReply.recipient_id, func.count(),
        func.sum(case((_day_sql(db, SeniorReply.created_at) == today, 1), else_=0)),
    ).where(SeniorReply.user_id == owner_id, SeniorReply.recipient_id.in_(recipient_ids))
        .group_by(SeniorReply.recipient_id)).all()
    for recipient_id, count, today_count in replies:
        stats[recipient_id].update(reply_count=count, today_reply_count=int(today_count or 0))
    activities = union_all(
        select(Message.recipient_id.label("recipient_id"), timestamp.label("at"),
               case((Message.script != "", Message.script), else_=Message.memo).label("preview"))
        .where(Message.user_id == owner_id, Message.recipient_id.in_(recipient_ids), Message.status != "deleted"),
        select(SeniorReply.recipient_id, SeniorReply.created_at, SeniorReply.text)
        .where(SeniorReply.user_id == owner_id, SeniorReply.recipient_id.in_(recipient_ids)),
    ).subquery()
    ranked = select(
        activities.c.recipient_id, activities.c.at, activities.c.preview,
        func.row_number().over(partition_by=activities.c.recipient_id,
                               order_by=(activities.c.at.desc(), activities.c.preview.desc())).label("rank"),
    ).subquery()
    for recipient_id, at, preview in db.execute(select(
        ranked.c.recipient_id, ranked.c.at, ranked.c.preview,
    ).where(ranked.c.rank == 1)):
        stats[recipient_id].update(last_activity_at=iso(at), last_preview=(preview or "")[:80])
    return stats


def recipient_dict(db: Session, recipient: Recipient, public: bool = False, stats: dict | None = None) -> dict:
    result = {
        "id": recipient.id, "nickname": recipient.nickname, "relation": recipient.relation,
        "child_name": recipient.child_name,
    }
    if public:
        return result
    stats = stats if stats is not None else recipient_summaries(db, [recipient])[recipient.id]
    result.update({
        **{key: getattr(recipient, key) for key in PROFILE_FIELDS},
        "is_primary": recipient.legacy_parent_id is not None,
        **stats,
    })
    return result


def reply_event(reply: SeniorReply) -> dict:
    return {
        "type": "reply", "id": reply.id, "created_at": iso(reply.created_at),
        "date": korea_date(reply.created_at), "text": reply.text, "message_id": reply.message_id,
    }


def video_event(db: Session, message: Message, token: str | None = None) -> dict:
    if token is None:
        from ..serialize import message as serialize_message
        data = serialize_message(db, message)
    else:
        root = f"/api/watch/{token}/messages/{message.id}"
        data = {
            "id": message.id, "recipient_id": message.recipient_id,
            "script": message.script, "status": message.status,
            "duration": message.duration, "captions": message.captions or [],
            "video_url": f"{root}/video" if message.video_path else None,
            "poster_url": f"{root}/poster" if message.poster_path else None,
            "created_at": iso(message.created_at), "approved_at": iso(message.approved_at),
            "sent_at": iso(message.sent_at), "viewed_at": iso(message.viewed_at),
        }
    return {"type": "video", "id": message.id, "created_at": iso(video_time(message)),
            "date": korea_date(video_time(message)), "message": data}


def _event_key(event: dict) -> tuple[str, str, int]:
    timestamp = datetime.fromisoformat(event["created_at"].replace("Z", "+00:00"))
    return timestamp.isoformat(timespec="microseconds"), event["type"], event["id"]


def _cursor(event: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(_event_key(event), separators=(",", ":")).encode()).decode().rstrip("=")


def _parse_cursor(value: str) -> tuple[str, str, int]:
    try:
        if len(value) > 200:
            raise ValueError
        parsed = json.loads(base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)))
        if (not isinstance(parsed, list) or len(parsed) != 3 or not isinstance(parsed[0], str)
                or parsed[1] not in ("video", "reply") or not isinstance(parsed[2], int)):
            raise ValueError
        parsed_time = datetime.fromisoformat(parsed[0].replace("Z", "+00:00"))
        if parsed_time.tzinfo is None:
            raise ValueError
        parsed[0] = parsed_time.astimezone(timezone.utc).isoformat(timespec="microseconds")
        return tuple(parsed)
    except (ValueError, TypeError, OverflowError, json.JSONDecodeError, UnicodeDecodeError):
        raise HTTPException(422, "대화 페이지 정보가 올바르지 않아요.")


def conversation(db: Session, recipient: Recipient, selected_date: str | None = None,
                 token: str | None = None, before: str | None = None, limit: int = 100) -> dict:
    selected_date, start, end = day_bounds(selected_date)
    timestamp = func.coalesce(Message.approved_at, Message.created_at)
    query = select(Message).where(Message.user_id == recipient.user_id, Message.recipient_id == recipient.id)
    query = query.where(Message.status.in_(WATCHABLE)) if token else query.where(Message.status != "deleted")
    reply_query = select(SeniorReply).where(
        SeniorReply.user_id == recipient.user_id, SeniorReply.recipient_id == recipient.id,
    )
    days = defaultdict(lambda: {"video_count": 0, "reply_count": 0})
    video_day = _day_sql(db, timestamp)
    reply_day = _day_sql(db, SeniorReply.created_at)
    for day, count in db.execute(query.with_only_columns(video_day, func.count()).group_by(video_day)):
        days[str(day)]["video_count"] = count
    for day, count in db.execute(reply_query.with_only_columns(reply_day, func.count()).group_by(reply_day)):
        days[str(day)]["reply_count"] = count
    query = query.where(timestamp >= start, timestamp < end)
    reply_query = reply_query.where(SeniorReply.created_at >= start, SeniorReply.created_at < end)
    if before:
        cursor_time, cursor_type, cursor_id = _parse_cursor(before)
        cursor_dt = datetime.fromisoformat(cursor_time).astimezone(timezone.utc).replace(tzinfo=None)
        query = query.where(or_(timestamp < cursor_dt,
                                and_(timestamp == cursor_dt, Message.id < cursor_id) if cursor_type == "video" else False))
        reply_query = reply_query.where(or_(
            SeniorReply.created_at < cursor_dt,
            and_(SeniorReply.created_at == cursor_dt,
                 SeniorReply.id < cursor_id if cursor_type == "reply" else True),
        ))
    messages = db.scalars(query.order_by(timestamp.desc(), Message.id.desc()).limit(limit + 1)).all()
    replies = db.scalars(reply_query.order_by(SeniorReply.created_at.desc(), SeniorReply.id.desc()).limit(limit + 1)).all()
    # Select the page before serializing videos, which can fetch their generation metadata.
    selected = [(video_time(message), "video", message.id, message) for message in messages]
    selected += [(reply.created_at, "reply", reply.id, reply) for reply in replies]
    selected.sort(key=lambda value: value[:3])
    has_more = len(selected) > limit
    selected = selected[-limit:]
    events = [video_event(db, row, token) if kind == "video" else reply_event(row)
              for _at, kind, _id, row in selected]
    events.sort(key=_event_key)
    return {
        "recipient": recipient_dict(db, recipient, public=bool(token)), "child_name": recipient.child_name,
        "today": korea_date(), "selected_date": selected_date, "timezone": "Asia/Seoul",
        "days": [{"date": day, **days[day]} for day in sorted(days, reverse=True)],
        "events": events, "has_more": has_more,
        "next_before": _cursor(events[0]) if has_more and events else None,
    }


TOPICS = {
    "식사와 음식": ("밥", "식사", "먹", "맛있", "음식", "반찬", "국수", "김치"),
    "가족과 안부": ("엄마", "아빠", "아들", "딸", "손주", "손자", "손녀", "가족", "보고 싶", "보고싶", "안부", "사랑"),
    "일상과 활동": ("산책", "운동", "시장", "친구", "모임", "여행", "공원", "나들이", "텃밭", "경로당"),
    "몸 상태와 휴식": ("아프", "아파", "병원", "약", "피곤", "잠", "쉬", "건강", "무릎", "허리"),
    "날씨와 계절": ("날씨", "춥", "추워", "덥", "더워", "바람", "햇살", "봄", "여름", "가을", "겨울", "비가", "눈이"),
    "고마움과 응원": ("고마", "감사", "잘했", "수고", "힘내", "응원", "기특", "대견"),
}


def reply_topics(text: str) -> list[str]:
    return [name for name, words in TOPICS.items() if any(word in text for word in words)]


def reply_fingerprint(replies: list[SeniorReply]) -> str:
    data = [[reply.id, reply.text, iso(reply.created_at)] for reply in replies]
    return hashlib.sha256(json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def _evidence(reply: SeniorReply) -> dict:
    return {"reply_id": reply.id, "text": reply.text, "date": korea_date(reply.created_at)}


def build_portfolio(recipient: Recipient, month: str, replies: list[SeniorReply]) -> dict:
    """Describe observed wording and participation, never infer diagnoses or health scores."""
    by_day = defaultdict(list)
    by_topic = defaultdict(list)
    for reply in replies:
        by_day[korea_date(reply.created_at)].append(reply)
        for topic in reply_topics(reply.text):
            by_topic[topic].append(reply)
    topics = [{"name": name, "count": len(values), "evidence": [_evidence(reply) for reply in values[:3]]}
              for name, values in sorted(by_topic.items(), key=lambda item: (-len(item[1]), item[0]))]
    daily = []
    for day, values in sorted(by_day.items()):
        counts = Counter(topic for reply in values for topic in reply_topics(reply.text))
        daily.append({"date": day, "reply_count": len(values), "characters": sum(len(reply.text) for reply in values),
                      "topics": [topic for topic, _count in counts.most_common(3)]})
    representatives = []
    seen = set()
    for values in by_day.values():
        reply = max(values, key=lambda item: (len(reply_topics(item.text)), len(item.text), -item.id))
        if reply.text not in seen:
            representatives.append(_evidence(reply))
            seen.add(reply.text)
        if len(representatives) >= 8:
            break
    main_topics = ", ".join(topic["name"] for topic in topics[:3]) or "등록된 주제 키워드에 해당하지 않는 일상 이야기"
    summary = f"{month}에는 {len(by_day)}일에 걸쳐 답글 {len(replies)}개를 주고받았어요. 답글에서 자주 확인된 주제는 {main_topics}예요."
    if len(replies) < 10:
        summary += " 아직 답글이 적어 한 달의 생활 전반을 설명하기에는 기록이 부족해요."
    starters = {
        "식사와 음식": "최근 맛있게 드신 음식이나 다음에 함께 먹고 싶은 음식을 여쭤보세요.",
        "가족과 안부": "함께 기억하는 가족 이야기나 다음 만남에 대해 물어보세요.",
        "일상과 활동": "최근 다녀오신 곳이나 즐거웠던 활동 이야기를 이어가 보세요.",
        "몸 상태와 휴식": "편하게 쉬셨는지, 일상에서 도움이 필요한 일이 있는지 직접 여쭤보세요.",
        "날씨와 계절": "계절 풍경이나 오늘 날씨 이야기를 나눠 보세요.",
        "고마움과 응원": "전해 주신 응원에 고마움을 담아 답해 보세요.",
    }
    return {
        "source": "local_evidence_v1", "title": f"{recipient.nickname}님의 {month} 대화 포트폴리오",
        "summary": summary, "reply_count": len(replies), "active_days": len(by_day),
        "days_in_month": calendar.monthrange(*map(int, month.split("-")))[1],
        "topics": topics, "daily_trends": daily, "representative_replies": representatives,
        "conversation_starters": [starters[topic["name"]] for topic in topics[:3]] or ["최근 어떻게 지내셨는지 편하게 여쭤보세요."],
        "caveats": [
            "대화에 직접 남긴 답글만 정리한 기록이며 건강 상태, 감정, 인지 능력에 대한 진단이나 평가가 아닙니다.",
            "주제는 정해진 한국어 키워드의 포함 여부로 집계합니다. 문맥, 부정 표현, 말투를 완전히 이해하지 못할 수 있습니다.",
            "하나의 답글이 여러 주제에 포함될 수 있습니다. 주제의 개수는 답글의 개수와 다를 수 있습니다.",
            "답글이 없는 날의 상태는 알 수 없습니다. 공유 링크를 가진 사람이 작성했으며 작성자의 신원은 인증하지 않았습니다.",
            "현재 월의 보고서는 작성 시점까지의 부분 기록입니다. 새 답글이 오면 다시 작성해 주세요.",
        ],
    }


def portfolio_state(db: Session, recipient: Recipient, month: str | None = None, generate: bool = False) -> dict:
    month, start, end = month_bounds(month)
    if generate:
        lock_owner(db, recipient.user_id)
    replies = db.scalars(select(SeniorReply).where(
        SeniorReply.recipient_id == recipient.id, SeniorReply.user_id == recipient.user_id,
        SeniorReply.created_at >= start, SeniorReply.created_at < end,
    ).order_by(SeniorReply.created_at, SeniorReply.id)).all()
    row = db.scalar(select(MonthlyPortfolio).where(
        MonthlyPortfolio.recipient_id == recipient.id, MonthlyPortfolio.user_id == recipient.user_id,
        MonthlyPortfolio.month == month,
    ))
    fingerprint = reply_fingerprint(replies)
    if generate:
        if not replies:
            raise HTTPException(409, "이번 달에 쌓인 답글이 있어야 포트폴리오를 작성할 수 있어요.")
        report = build_portfolio(recipient, month, replies)
        if row is None:
            try:
                with db.begin_nested():
                    row = MonthlyPortfolio(user_id=recipient.user_id, recipient_id=recipient.id,
                                           month=month, source_fingerprint=fingerprint, report=report)
                    db.add(row)
                    db.flush()
            except IntegrityError:
                row = db.scalar(select(MonthlyPortfolio).where(
                    MonthlyPortfolio.recipient_id == recipient.id, MonthlyPortfolio.month == month,
                ))
                if row is None:
                    raise
        row.report = report
        row.source_fingerprint = fingerprint
        row.source_reply_count = len(replies)
        row.source_latest_reply_id = max(reply.id for reply in replies)
        row.generated_at = utcnow()
        db.commit()
    reply_month = func.substr(_day_sql(db, SeniorReply.created_at), 1, 7)
    reply_months = db.scalars(select(reply_month).where(
        SeniorReply.recipient_id == recipient.id, SeniorReply.user_id == recipient.user_id,
    ).group_by(reply_month)).all()
    saved_months = db.scalars(select(MonthlyPortfolio.month).where(
        MonthlyPortfolio.recipient_id == recipient.id, MonthlyPortfolio.user_id == recipient.user_id,
    )).all()
    return {
        "recipient_id": recipient.id, "month": month,
        "available_months": sorted(set(reply_months) | set(saved_months) | {month}, reverse=True),
        "reply_count": len(replies), "active_days": len({korea_date(reply.created_at) for reply in replies}),
        "stale": bool(row and row.source_fingerprint != fingerprint),
        "portfolio": {**row.report, "id": row.id, "generated_at": iso(row.generated_at)} if row else None,
    }


def refresh_closed_portfolios(db: Session, limit: int = 25) -> int:
    """Worker catch-up: persist each completed Korea calendar month, including missed runs."""
    current_month, start, _end = month_bounds()
    reply_month = func.substr(_day_sql(db, SeniorReply.created_at), 1, 7)
    groups = db.execute(select(
        SeniorReply.recipient_id, reply_month.label("month"), func.count(), func.max(SeniorReply.id),
    ).where(SeniorReply.created_at < start).group_by(SeniorReply.recipient_id, reply_month)
        .order_by(reply_month, SeniorReply.recipient_id)).all()
    if not groups:
        return 0
    recipient_ids = {recipient_id for recipient_id, _month, _count, _latest in groups}
    saved = {(row.recipient_id, row.month): row for row in db.scalars(select(MonthlyPortfolio)
             .where(MonthlyPortfolio.recipient_id.in_(recipient_ids), MonthlyPortfolio.month < current_month)).all()}
    changed = 0
    for recipient_id, month, count, latest in groups:
        row = saved.get((recipient_id, month))
        if row and row.source_reply_count == count and row.source_latest_reply_id == latest:
            continue
        recipient = db.get(Recipient, recipient_id)
        if recipient:
            portfolio_state(db, recipient, month, generate=True)
            changed += 1
        if changed >= limit:
            break
    return changed
