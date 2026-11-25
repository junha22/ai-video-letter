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

from .private_images import image_info
from ..config import settings
from ..db import iso, utcnow
from ..models import Message, MonthlyPortfolio, Notification, ParentProfile, Recipient, SeniorReply, User

KOREA = timezone(timedelta(hours=9), "Asia/Seoul")
WATCHABLE = ("approved", "sent", "viewed")
PROFILE_FIELDS = ("nickname", "relation", "phone", "child_call_name", "speech_level", "tone_examples")
# Owner chat feed: the first screen and each "earlier" page hold this many days that have chat,
# capped by event count (a single day is never split, so one busy day can exceed the cap).
FEED_DAYS = 3
FEED_MAX_EVENTS = 150


def korea_date(value: datetime | None = None) -> str:
    value = value or utcnow()
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(KOREA).date().isoformat()


def _day_start(value: str) -> datetime:
    """UTC (naive) instant of Korea midnight for YYYY-MM-DD; 422 on a malformed date."""
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise HTTPException(422, "날짜는 YYYY-MM-DD 형식이어야 해요.")
    try:
        parsed = date.fromisoformat(value)
        start = datetime(parsed.year, parsed.month, parsed.day, tzinfo=KOREA).astimezone(timezone.utc).replace(tzinfo=None)
        start + timedelta(days=1)  # the next midnight must be representable too
    except (ValueError, OverflowError):
        raise HTTPException(422, "올바른 날짜를 선택해 주세요.")
    return start


def day_bounds(value: str | None = None) -> tuple[str, datetime, datetime]:
    value = value or korea_date()
    start = _day_start(value)
    if value > korea_date():
        raise HTTPException(422, "오늘 이후의 대화는 아직 없어요.")
    return value, start, start + timedelta(days=1)


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
        # 받아쓰기 전(또는 불확실한) 음성 답장은 글이 비어 있다
        select(SeniorReply.recipient_id, SeniorReply.created_at,
               case((SeniorReply.text == "", "음성 답장"), else_=SeniorReply.text))
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
    result["photo"] = image_info(recipient.photo, f"/api/recipients/{recipient.id}/photo/image")
    if settings.reply_analysis_enabled:
        from .replies import owner_state
        result["reply_analysis"] = owner_state(db, recipient)
    return result


def reply_event(reply: SeniorReply, token: str | None = None) -> dict:
    event = {
        "type": "reply", "id": reply.id, "created_at": iso(reply.created_at),
        "date": korea_date(reply.created_at), "text": reply.text, "message_id": reply.message_id,
    }
    if reply.kind == "voice":
        root = f"/api/watch/{token}/replies/{reply.id}" if token else f"/api/recipients/{reply.recipient_id}/replies/{reply.id}"
        event.update(kind="voice", audio_url=f"{root}/audio", audio_seconds=reply.audio_seconds)
        if token:
            event["text"] = ""  # 시니어 화면에는 자동 받아쓰기를 보여 주지 않는다 (docs/REPLY_ANALYSIS.md)
    return event


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


def _room_queries(recipient: Recipient, token: str | None = None):
    """Videos and replies of one room: the public link sees only watchable videos, the owner every kept one."""
    query = select(Message).where(Message.user_id == recipient.user_id, Message.recipient_id == recipient.id)
    query = query.where(Message.status.in_(WATCHABLE)) if token else query.where(Message.status != "deleted")
    reply_query = select(SeniorReply).where(
        SeniorReply.user_id == recipient.user_id, SeniorReply.recipient_id == recipient.id,
    )
    return query, reply_query


def _day_counts(db: Session, query, reply_query) -> dict[str, dict]:
    """Korea calendar days that have chat, with video and reply counts."""
    timestamp = func.coalesce(Message.approved_at, Message.created_at)
    days = defaultdict(lambda: {"video_count": 0, "reply_count": 0})
    video_day = _day_sql(db, timestamp)
    reply_day = _day_sql(db, SeniorReply.created_at)
    for day, count in db.execute(query.with_only_columns(video_day, func.count()).group_by(video_day)):
        days[str(day)]["video_count"] = count
    for day, count in db.execute(reply_query.with_only_columns(reply_day, func.count()).group_by(reply_day)):
        days[str(day)]["reply_count"] = count
    return days


def conversation(db: Session, recipient: Recipient, selected_date: str | None = None,
                 token: str | None = None, before: str | None = None, limit: int = 100) -> dict:
    selected_date, start, end = day_bounds(selected_date)
    timestamp = func.coalesce(Message.approved_at, Message.created_at)
    query, reply_query = _room_queries(recipient, token)
    days = _day_counts(db, query, reply_query)
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
    events = [video_event(db, row, token) if kind == "video" else reply_event(row, token)
              for _at, kind, _id, row in selected]
    events.sort(key=_event_key)
    if not token:  # 답장 분석은 자녀(로그인 사용자)에게만
        from .replies import attach
        attach(db, recipient.user_id, events)
    return {
        "recipient": recipient_dict(db, recipient, public=bool(token)), "child_name": recipient.child_name,
        "today": korea_date(), "selected_date": selected_date, "timezone": "Asia/Seoul",
        "days": [{"date": day, **days[day]} for day in sorted(days, reverse=True)],
        "events": events, "has_more": has_more,
        "next_before": _cursor(events[0]) if has_more and events else None,
    }


def conversation_feed(db: Session, recipient: Recipient, before: str | None = None, after: str | None = None,
                      page_days: int = FEED_DAYS, max_events: int = FEED_MAX_EVENTS, token: str | None = None) -> dict:
    """Chat feed paged by whole days that have chat, for the owner or (with token) the recipient's link.

    No bound: the latest days. before=D: the days just before D (scrolling up). after=D: the days just
    after D (jumping to a date passes the day before it, then reading on). Days without chat are skipped.
    The link sees only watchable videos, with media addressed through the token.
    """
    if before and after:
        raise HTTPException(422, "before와 after는 함께 쓸 수 없어요.")
    if before:
        _day_start(before)
    if after:
        _day_start(after)
    query, reply_query = _room_queries(recipient, token)
    counts = _day_counts(db, query, reply_query)
    active = sorted(counts)
    if after:
        candidates = [day for day in active if day > after]
    else:
        candidates = [day for day in reversed(active) if before is None or day < before]
    picked, total = [], 0
    for day in candidates:
        size = counts[day]["video_count"] + counts[day]["reply_count"]
        if picked and (len(picked) >= page_days or total + size > max_events):
            break
        picked.append(day)
        total += size
    picked.sort()

    events = []
    if picked:
        start, end = _day_start(picked[0]), _day_start(picked[-1]) + timedelta(days=1)
        timestamp = func.coalesce(Message.approved_at, Message.created_at)
        messages = db.scalars(query.where(timestamp >= start, timestamp < end)).all()
        replies = db.scalars(reply_query.where(SeniorReply.created_at >= start, SeniorReply.created_at < end)).all()
        events = [video_event(db, message, token) for message in messages] + [reply_event(reply, token) for reply in replies]
        events.sort(key=_event_key)
        if not token:  # 답장 분석은 자녀(로그인 사용자)에게만. 공개 링크에는 붙이지 않는다
            from .replies import attach
            attach(db, recipient.user_id, events)
        has_older, has_newer = active[0] < picked[0], active[-1] > picked[-1]
    else:
        # Nothing on this side of the bound: say whether the other side still has chat.
        has_older = bool(after) and bool(active) and active[0] <= after
        has_newer = bool(before) and bool(active) and active[-1] >= before
    return {
        "recipient": recipient_dict(db, recipient, public=bool(token)), "child_name": recipient.child_name,
        "today": korea_date(), "timezone": "Asia/Seoul",
        "days": [{"date": day, **counts[day]} for day in reversed(active)],
        "events": events, "start": picked[0] if picked else None, "end": picked[-1] if picked else None,
        "has_older": has_older, "has_newer": has_newer,
    }


def reply_fingerprint(replies: list[SeniorReply]) -> str:
    data = [[reply.id, reply.text, iso(reply.created_at)] for reply in replies]
    return hashlib.sha256(json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def build_portfolio(recipient: Recipient, month: str, replies: list[SeniorReply]) -> dict:
    """한 달의 답글 수·대화한 날만 정리한다 (진단·점수는 쓰지 않는다).
    local_evidence_v2 (2026-11-25): 키워드 주제·날짜별 흐름·대표 답글·대화 제안을 뺐다. 날짜별 흐름은 화면의 캘린더(portfolio_state의
    calendar), 주제는 답장 살펴보기를 켠 방의 '이번 달 나눈 이야기'(reply_month)가 맡는다. 예전에 저장한 v1 보고서의 그 칸은 화면이 쓰지 않는다."""
    days = {korea_date(reply.created_at) for reply in replies}
    voice = sum(1 for reply in replies if reply.kind == "voice")
    summary = f"{month}에는 {len(days)}일에 걸쳐 답글 {len(replies)}개를 주고받았어요."
    if voice:
        summary += f" 그중 음성 답장은 {voice}개예요."
    if len(replies) < 10:
        summary += " 아직 답글이 적어 한 달의 생활 전반을 설명하기에는 기록이 부족해요."
    return {
        "source": "local_evidence_v2", "title": f"{recipient.nickname}님의 {month} 대화 포트폴리오",
        "summary": summary, "reply_count": len(replies), "active_days": len(days),
        "days_in_month": calendar.monthrange(*map(int, month.split("-")))[1],
        "caveats": [
            "대화에 직접 남긴 답글만 정리한 기록이며 건강 상태, 감정, 인지 능력에 대한 진단이나 평가가 아닙니다.",
            "답글이 없는 날의 상태는 알 수 없습니다. 공유 링크를 가진 사람이 작성했으며 작성자의 신원은 인증하지 않았습니다.",
            "현재 월의 보고서는 작성 시점까지의 부분 기록입니다. 새 답글이 오면 다시 작성해 주세요.",
        ] + (["음성 답장은 자동 받아쓰기로 정리해서 틀린 글자가 있을 수 있습니다."] if voice else []),
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
    per_day = Counter(korea_date(reply.created_at) for reply in replies)
    return {
        "recipient_id": recipient.id, "month": month,
        "available_months": sorted(set(reply_months) | set(saved_months) | {month}, reverse=True),
        "reply_count": len(replies), "active_days": len(per_day),
        # 한 달 흐름 캘린더: 답글이 있는 날의 답글 수 (볼 때마다 센다. 위험도 색은 답장 살펴보기를 켠 방의 analysis_trends.days)
        "calendar": [{"date": day, "reply_count": per_day[day]} for day in sorted(per_day)],
        "stale": bool(row and row.source_fingerprint != fingerprint),
        "portfolio": {**row.report, "id": row.id, "generated_at": iso(row.generated_at)} if row else None,
    }


def delete_reply(db: Session, recipient: Recipient, reply_id: int) -> None:
    """Remove one reply with its notification preview and any saved report quoting it."""
    lock_owner(db, recipient.user_id)
    reply = db.get(SeniorReply, reply_id)
    if not reply or reply.user_id != recipient.user_id or reply.recipient_id != recipient.id:
        raise HTTPException(404, "답글을 찾을 수 없어요.")
    # Older notifications have no reply id; they were written with the reply and quote its first 60 characters.
    note = db.scalar(select(Notification).where(
        Notification.user_id == reply.user_id, Notification.recipient_id == recipient.id,
        Notification.kind == "senior_reply", Notification.created_at >= reply.created_at,
        Notification.reply_id.is_(None), Notification.text.endswith(f": {reply.text[:60]}", autoescape=True),
    ).order_by(Notification.created_at, Notification.id).limit(1))
    if note:
        db.delete(note)
    from .replies import delete_for_reply
    delete_for_reply(db, reply)  # 음성 파일, 답장 분석, reply_id로 이어진 알림
    month = korea_date(reply.created_at)[:7]
    db.delete(reply)
    db.flush()
    saved = db.scalar(select(MonthlyPortfolio).where(
        MonthlyPortfolio.recipient_id == recipient.id, MonthlyPortfolio.month == month,
    ))
    if saved:
        _month, start, end = month_bounds(month)
        remaining = db.scalar(select(func.count()).select_from(SeniorReply).where(
            SeniorReply.recipient_id == recipient.id, SeniorReply.created_at >= start, SeniorReply.created_at < end,
        ))
        if remaining:
            portfolio_state(db, recipient, month, generate=True)
        else:
            db.delete(saved)
    db.commit()


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
