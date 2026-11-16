"""부모님 답장 분석의 서비스 쪽: 동의, 음성 답장 저장, 분석 작업(reply_analysis), 자녀 화면용 결과, 삭제 (docs/REPLY_ANALYSIS.md).

판단 규칙은 reply_analysis.py에 있다. 음성 답장의 받아쓰기·운율은 GPU PC 분석 서버(reply_gpu.py),
LLM 판단은 CLOVA Studio HCX-007(reply_llm.py)이 한다 (2026-11-16, GPU PC 메모리가 모자라 로컬 SEED 14B에서 바꿈).
- REPLY_ANALYSIS_ENABLED가 꺼져 있으면 아무것도 하지 않는다 (음성 답장·분석·응답의 새 칸 없음).
- 자녀가 대상자별로 켜고(child) 시니어가 안내를 확인해야(senior) 분석한다. 지금 동의 문구 버전으로 받은 동의만 인정한다.
  안내 전에 온 답장은 거슬러 분석하지 않는다.
- CLOVA에는 답장 글(음성 답장은 자동 받아쓰기)·편지·최근 기록만 보내고, 전화번호·계좌번호·이메일·DB에 있는 이름은 가린다.
  음성 파일과 목소리 값, 사용자·대상자 ID는 보내지 않는다.
- 분석 결과는 자녀(로그인 사용자) 화면에만 보낸다. 공개 대화방 응답에는 넣지 않는다.
- 음성·받아쓰기·분석 결과는 로그에 남기지 않는다 (걸린 시간·상태만).
"""

import json
import logging
import time

from fastapi import HTTPException
from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.orm import Session

from ..config import settings
from ..db import iso, utcnow
from ..models import Job, Message, Notification, Recipient, ReplyAnalysis, ReplyAnalysisConsent, SeniorReply, User
from . import audio, jobs, reply_gpu, reply_llm, storage
from . import reply_analysis as rules
from .conversations import WATCHABLE, korea_date

log = logging.getLogger("ongi.replies")

VOICE_RATE = 16000              # 받아쓰기·운율 분석에 쓰는 16kHz 모노 (재생도 같은 파일)
MAX_VOICE_SECONDS = 180         # 3분. 녹음 화면도 3분에 멈춘다
MIN_VOICE_SECONDS = 1.0
MAX_VOICE_BYTES = 10 * 1024 * 1024
ANALYSIS_KINDS = ("reply_check", "reply_alert")
# 음성 답장 1개 분석에 걸리는 대략의 시간 (기다리는 영상 화면 안내용). 잰 값이 아니라 추정이다:
# 받아쓰기(모델 올리기 포함) 약 30초 + 운율 몇 초 + CLOVA 판단 10~20초
EXPECTED_SECONDS = 60

# 문구를 바꾸면 REPLY_ANALYSIS_CONSENT_VERSION도 바꾼다 (바꾸면 자녀·시니어에게 다시 묻는다)
CHILD_CONSENT_TEXT = (
    "부모님이 보낸 답장을 AI가 정리해 나에게만 보여 주는 것을 부모님께 알리고 동의를 받았어요. "
    "답장 글(음성 답장은 자동 받아쓰기 글)을 네이버 클로바(CLOVA Studio) AI로 보내 분석해요. "
    "음성 파일과 목소리 값은 보내지 않고, 이름·전화번호는 가려서 보내요. "
    "정리한 내용은 진단이 아니에요. 끄면 지금까지의 분석 결과를 지워요."
)


def senior_notice_text(child_name: str) -> str:
    return (f"보내 주신 목소리와 답장은 {child_name}님께 전달돼요. 답장 글(음성은 받아쓴 글)을 네이버 클로바(CLOVA Studio) "
            f"AI로 보내 정리하고, 정리한 내용은 {child_name}님께만 보여 드려요. 음성 파일은 보내지 않아요. 진단이 아니에요.")


# ---------------------------------------------------------------- 동의 ----
def parties(db: Session, user_id: int, recipient_id: int) -> set[str]:
    """지금 문구 버전으로 받은 동의만 센다. 버전을 올리면 예전 동의는 남아 있어도 다시 묻는다"""
    return set(db.scalars(select(ReplyAnalysisConsent.party).where(
        ReplyAnalysisConsent.user_id == user_id, ReplyAnalysisConsent.recipient_id == recipient_id,
        ReplyAnalysisConsent.withdrawn_at.is_(None),
        ReplyAnalysisConsent.version == settings.reply_analysis_consent_version,
    )).all())


def voice_available(db: Session, recipient: Recipient) -> bool:
    """시니어 화면에 녹음 버튼을 보일지: 기능이 켜져 있고 자녀가 이 대상자에 분석을 켰을 때"""
    return settings.reply_analysis_enabled and "child" in parties(db, recipient.user_id, recipient.id)


def analysis_allowed(db: Session, user_id: int, recipient_id: int) -> bool:
    return settings.reply_analysis_enabled and {"child", "senior"} <= parties(db, user_id, recipient_id)


def owner_state(db: Session, recipient: Recipient) -> dict:
    agreed = parties(db, recipient.user_id, recipient.id)
    return {"enabled": "child" in agreed, "senior_notice": "senior" in agreed,
            "consent_text": CHILD_CONSENT_TEXT, "version": settings.reply_analysis_consent_version}


def public_state(db: Session, recipient: Recipient) -> dict:
    agreed = parties(db, recipient.user_id, recipient.id)
    available = "child" in agreed
    return {"available": available, "notice_needed": available and "senior" not in agreed,
            "notice": senior_notice_text(recipient.child_name) if available else None,
            "max_seconds": MAX_VOICE_SECONDS}


def agree(db: Session, recipient: Recipient, party: str, share_link_id: int | None = None) -> None:
    if party not in parties(db, recipient.user_id, recipient.id):
        db.add(ReplyAnalysisConsent(user_id=recipient.user_id, recipient_id=recipient.id, party=party,
                                    version=settings.reply_analysis_consent_version, share_link_id=share_link_id))


def turn_off(db: Session, recipient: Recipient) -> dict:
    """자녀가 이 대상자의 분석을 끔: 두 동의를 철회하고, 분석 결과·분석 알림을 지우고, 대기 중인 분석을 취소한다.
    답장과 음성은 남긴다. 다시 켜면 시니어 안내도 다시 보인다."""
    now = utcnow()
    db.execute(update(ReplyAnalysisConsent).where(
        ReplyAnalysisConsent.user_id == recipient.user_id, ReplyAnalysisConsent.recipient_id == recipient.id,
        ReplyAnalysisConsent.withdrawn_at.is_(None),
    ).values(withdrawn_at=now))
    reply_ids = set(db.scalars(select(ReplyAnalysis.reply_id).where(
        ReplyAnalysis.user_id == recipient.user_id, ReplyAnalysis.recipient_id == recipient.id,
    )).all())
    _cancel_jobs(db, recipient.user_id, reply_ids)
    analyses = db.execute(delete(ReplyAnalysis).where(
        ReplyAnalysis.user_id == recipient.user_id, ReplyAnalysis.recipient_id == recipient.id,
    )).rowcount
    notes = db.execute(delete(Notification).where(
        Notification.user_id == recipient.user_id, Notification.recipient_id == recipient.id,
        Notification.kind.in_(ANALYSIS_KINDS),
    )).rowcount
    return {"reply_analyses": analyses, "analysis_notifications": notes}


def _cancel_jobs(db: Session, user_id: int, reply_ids: set[int]) -> None:
    if not reply_ids:
        return
    for job in db.scalars(select(Job).where(Job.user_id == user_id, Job.type == "reply_analysis", Job.status == "queued")):
        if (job.payload or {}).get("reply_id") in reply_ids:
            job.status, job.finished_at = "canceled", utcnow()


# ---------------------------------------------------------------- 음성 답장 ----
def decode_voice(data: bytes) -> tuple:
    """업로드한 녹음(webm/mp4 …)을 16kHz 모노로. 소리 크기는 그대로 둔다 (목소리 크기를 평소와 비교하므로 정규화하지 않는다)"""
    if len(data) > MAX_VOICE_BYTES:
        raise HTTPException(413, "녹음 파일이 너무 커요.")
    try:
        samples = audio.decode(data, rate=VOICE_RATE)
    except RuntimeError:
        raise HTTPException(400, "녹음을 읽을 수 없어요. 다시 녹음해 주세요.")
    seconds = len(samples) / VOICE_RATE
    if seconds < MIN_VOICE_SECONDS:
        raise HTTPException(400, "녹음이 너무 짧아요. 다시 녹음해 주세요.")
    if seconds > MAX_VOICE_SECONDS + 2:  # 녹음 화면이 3분에 멈추는 사이의 오차
        raise HTTPException(413, "녹음은 3분까지 보낼 수 있어요.")
    return samples, round(seconds, 1)


def save_voice(reply: SeniorReply, samples) -> None:
    path = storage.user_dir(reply.user_id, "replies") / f"{reply.id}.wav"
    audio.write_wav(path, samples, rate=VOICE_RATE)
    reply.audio_path = storage.rel_path(path)


def queue(db: Session, reply: SeniorReply) -> ReplyAnalysis | None:
    """답장 저장과 같은 트랜잭션에서 분석을 넣는다. 답장마다 따로 돌아야 해서 같은 종류의 대기 작업을 바꿔치기하지 않는다"""
    if not analysis_allowed(db, reply.user_id, reply.recipient_id):
        return None
    row = ReplyAnalysis(user_id=reply.user_id, recipient_id=reply.recipient_id, reply_id=reply.id, kind=reply.kind,
                        status="queued", prompt_id=rules.PROMPT_ID)
    db.add(row)
    jobs.enqueue(db, "reply_analysis", reply.user_id, payload={"reply_id": reply.id}, replace=False)
    return row


def retry(db: Session, recipient: Recipient, reply_id: int) -> ReplyAnalysis:
    """실패한 분석 다시 하기 (GPU PC가 꺼져 있었거나 CLOVA에 연결하지 못했을 때 등)"""
    row = db.scalar(select(ReplyAnalysis).where(
        ReplyAnalysis.reply_id == reply_id, ReplyAnalysis.user_id == recipient.user_id,
        ReplyAnalysis.recipient_id == recipient.id,
    ))
    if not row:
        raise HTTPException(404, "분석한 답장이 아니에요.")
    if row.status != "failed":
        raise HTTPException(409, "정리하지 못한 답장만 다시 정리할 수 있어요.")
    if not analysis_allowed(db, recipient.user_id, recipient.id):
        raise HTTPException(409, "답장 살펴보기가 꺼져 있어요.")
    row.status, row.error, row.finished_at = "queued", None, None
    jobs.enqueue(db, "reply_analysis", recipient.user_id, payload={"reply_id": reply_id}, replace=False)
    return row


# ---------------------------------------------------------------- 자녀 화면 ----
def serialize(row: ReplyAnalysis | None) -> dict | None:
    if row is None:
        return None
    return {**rules.display(row.status, row.kind, row.result, row.voice),
            "can_retry": row.status == "failed", "finished_at": iso(row.finished_at)}


def attach(db: Session, user_id: int, events: list[dict]) -> list[dict]:
    """자녀(로그인 사용자) 대화의 답장 이벤트에 분석을 붙인다. 공개 대화방에서는 부르지 않는다"""
    if not settings.reply_analysis_enabled:
        return events
    ids = [event["id"] for event in events if event["type"] == "reply"]
    rows = {row.reply_id: row for row in db.scalars(select(ReplyAnalysis).where(
        ReplyAnalysis.user_id == user_id, ReplyAnalysis.reply_id.in_(ids),
    ))} if ids else {}
    for event in events:
        if event["type"] == "reply":
            event["analysis"] = serialize(rows.get(event["id"]))
    return events


# ---------------------------------------------------------------- 삭제 ----
def delete_for_reply(db: Session, reply: SeniorReply) -> None:
    """답장 하나 지우기: 음성 파일, 분석, 그 답장의 알림"""
    storage.delete_file(reply.audio_path)
    db.execute(delete(ReplyAnalysis).where(ReplyAnalysis.reply_id == reply.id))
    db.execute(delete(Notification).where(Notification.user_id == reply.user_id, Notification.reply_id == reply.id))


def delete_for_user(db: Session, user_id: int) -> dict:
    """동의 철회: 답장보다 먼저 부른다 (답장을 지우면 분석이 같이 지워져서 건수를 셀 수 없다)"""
    files = storage.delete_tree(settings.data_dir / "users" / str(user_id) / "replies")
    analyses = db.execute(delete(ReplyAnalysis).where(ReplyAnalysis.user_id == user_id)).rowcount
    notes = db.execute(delete(Notification).where(
        Notification.user_id == user_id, Notification.kind.in_(ANALYSIS_KINDS),
    )).rowcount
    db.execute(update(ReplyAnalysisConsent).where(
        ReplyAnalysisConsent.user_id == user_id, ReplyAnalysisConsent.withdrawn_at.is_(None),
    ).values(withdrawn_at=utcnow()))
    return {"reply_audio_files": files, "reply_analyses": analyses, "analysis_notifications": notes}


# ---------------------------------------------------------------- 분석 작업 ----
def _current(db: Session, user_id: int, reply_id: int | None) -> tuple[SeniorReply, ReplyAnalysis] | None:
    """답장·분석이 아직 그대로이고 동의도 그대로인지. 긴 HTTP 호출 뒤마다 다시 본다 (그사이 지웠거나 철회했으면 버린다)"""
    db.expire_all()
    reply = db.get(SeniorReply, reply_id) if reply_id else None
    if not reply or reply.user_id != user_id:
        return None
    row = db.scalar(select(ReplyAnalysis).where(ReplyAnalysis.reply_id == reply.id, ReplyAnalysis.user_id == user_id))
    if not row or not {"child", "senior"} <= parties(db, user_id, reply.recipient_id):
        return None
    return reply, row


def _before(reply: SeniorReply):
    return or_(SeniorReply.created_at < reply.created_at,
               and_(SeniorReply.created_at == reply.created_at, SeniorReply.id < reply.id))


def _earlier(db: Session, reply: SeniorReply, *conditions, limit: int):
    """같은 대상자의 이 답장보다 앞선 분석 (오래된 것부터)"""
    rows = db.execute(
        select(ReplyAnalysis, SeniorReply.created_at).join(SeniorReply, SeniorReply.id == ReplyAnalysis.reply_id)
        .where(ReplyAnalysis.user_id == reply.user_id, ReplyAnalysis.recipient_id == reply.recipient_id,
               _before(reply), *conditions)
        .order_by(SeniorReply.created_at.desc(), SeniorReply.id.desc()).limit(limit)
    ).all()
    return list(reversed(rows))


def history(db: Session, reply: SeniorReply) -> list[dict]:
    """LLM에 넣고 흐름 비교에 쓰는 최근 기록: 끝난 분석 3개 (history_text 형식)"""
    return [{"date": korea_date(at), **{k: row.result.get(k) for k in ("mood", "health", "mind", "life", "level", "summary")},
             "reply_chars": row.reply_chars}
            for row, at in _earlier(db, reply, ReplyAnalysis.status == "done", limit=rules.N_HISTORY)]


def past_prosody(db: Session, reply: SeniorReply) -> list[dict]:
    """평소 목소리: 이전 음성 답장 중 운율을 잰 것 (compare_prosody가 최근 10개를 쓴다)"""
    rows = _earlier(db, reply, ReplyAnalysis.kind == "voice", limit=50)
    return [row.prosody for row, _at in rows if row.prosody and row.prosody.get("ok")]


def letter(db: Session, reply: SeniorReply) -> str:
    """CLOVA에 넣는 자녀 편지: 답장이 가리킨 영상의 대본, 없으면 그 답장 전 이 대화방의 마지막 승인 영상 대본"""
    if reply.message_id:
        message = db.get(Message, reply.message_id)
        if message and message.user_id == reply.user_id:
            return message.script or ""
    message = db.scalars(select(Message).where(
        Message.user_id == reply.user_id, Message.recipient_id == reply.recipient_id, Message.status.in_(WATCHABLE),
        func.coalesce(Message.approved_at, Message.created_at) <= reply.created_at,
    ).order_by(func.coalesce(Message.approved_at, Message.created_at).desc(), Message.id.desc()).limit(1)).first()
    return message.script if message else ""


def hidden_names(db: Session, reply: SeniorReply) -> list[str]:
    """CLOVA로 보내기 전에 가릴 이름: 자녀 계정 이름, 부모님이 자녀를 부르는 이름, 대상자 호칭이 이름일 때.
    '엄마'·'아버지' 같은 호칭은 그대로 둔다"""
    recipient = db.get(Recipient, reply.recipient_id)
    user = db.get(User, reply.user_id)
    return reply_llm.names_to_hide(user.name if user else None, recipient.child_call_name if recipient else None,
                                   recipient.nickname if recipient else None)


def _finish(row: ReplyAnalysis, status: str, error: str | None = None) -> None:
    row.status, row.error, row.finished_at = status, error, utcnow()


def _notify(db: Session, reply: SeniorReply, level: str) -> None:
    """살펴보기 이상이면 알림. 알림 글에는 요약·받아쓰기를 넣지 않는다 (브라우저·휴대폰 알림 센터에 그대로 보일 수 있다)"""
    if level not in ("살펴보기", "바로 연락 필요"):
        return
    recipient = db.get(Recipient, reply.recipient_id)
    name = recipient.nickname if recipient else "부모"
    urgent = level == "바로 연락 필요"
    db.add(Notification(
        user_id=reply.user_id, recipient_id=reply.recipient_id, message_id=reply.message_id, reply_id=reply.id,
        kind="reply_alert" if urgent else "reply_check",
        text=f"{name}님 답장을 확인하고 바로 연락해 보세요" if urgent else f"{name}님 답장에 살펴볼 내용이 있어요",
    ))


def run(db: Session, job: Job) -> None:
    """답장 1개 분석. 음성: 받아쓰기 → (불확실하면 끝) → 운율 → 평소 비교 → CLOVA → 후처리. 글: CLOVA → 후처리
    (글 답장은 GPU PC가 꺼져 있어도 분석된다)"""
    reply_id = (job.payload or {}).get("reply_id")
    current = _current(db, job.user_id, reply_id)
    if not current:
        return
    reply, row = current
    if not settings.reply_analysis_enabled:  # 작업을 넣은 뒤 기능을 껐으면 정리하지 않고 끝낸다
        _finish(row, "failed", "REPLY_ANALYSIS_ENABLED가 꺼져 있어요")
        db.commit()
        return
    if not reply_llm.api_key():  # 받아쓰기(GPU)까지 하고 나서 실패하지 않게 먼저 본다
        raise reply_gpu.AnalysisError("CLOVA 키가 없어요 (REPLY_LLM_API_KEY 또는 NAVER_API_KEY)", retryable=False)
    row.status, row.error, row.finished_at = "running", None, None
    db.commit()
    started = time.monotonic()
    timings, voice, text = {}, None, reply.text

    if reply.kind == "voice":
        wav = storage.abs_path(reply.audio_path) if reply.audio_path else None
        if not wav or not wav.exists():
            raise reply_gpu.AnalysisError("음성 답장 파일이 없어요", retryable=False)
        t = time.monotonic()
        stt = reply_gpu.stt(wav)
        timings.update(stt=round(time.monotonic() - t, 1), stt_load=stt.get("load_seconds"))
        if not (current := _current(db, job.user_id, reply_id)):
            return
        reply, row = current
        row.stt_text = stt.get("text", "")
        row.stt = {k: stt.get(k) for k in ("duration", "pieces", "problems", "seconds", "load_seconds", "gpu_peak_gb")}
        row.stt_model = stt.get("model")
        if stt.get("problems"):
            # 받아쓰기가 불확실하면 LLM에 보내지 않고, 운율도 재지 않는다 (잡음 녹음이 평소 목소리에 섞이지 않게)
            row.timings = {**timings, "total": round(time.monotonic() - started, 1)}
            _finish(row, "stt_uncertain")
            db.commit()
            log.info("답장 분석 #%s: 받아쓰기 불확실 (%.1f초)", reply.id, time.monotonic() - started)
            return
        text = stt["text"]
        if not reply.text:
            reply.text = text  # 월별 포트폴리오와 다음 영상 대본에도 쓰인다 (kind=voice면 자동 받아쓰기)
        db.commit()
        t = time.monotonic()
        prosody = reply_gpu.prosody(wav, text)
        timings["prosody"] = round(time.monotonic() - t, 1)
        if not (current := _current(db, job.user_id, reply_id)):
            return
        reply, row = current
        voice = rules.compare_prosody(prosody, past_prosody(db, reply))
        row.prosody, row.voice = prosody, voice
        db.commit()

    # CLOVA Studio 약관상 개인정보는 넣지 않는다: 전화번호·계좌번호(mask_pii), 이메일·DB에 있는 이름([이름])을 가린다.
    # 후처리의 근거 비교도 CLOVA가 본 글과 같은 글로 해야 해서 가린 글을 그대로 쓴다
    names = hidden_names(db, reply)
    masked = reply_llm.hide_names(rules.mask_pii(text), names)
    hist = history(db, reply)
    user = reply_llm.hide_names(rules.user_prompt(reply_llm.hide_names(letter(db, reply), names), hist, masked), names)
    llm = reply_llm.analyze(rules.SYSTEM, user, rules.SCHEMA, rules.CLOVA_PARAMS)  # check_output까지 마친 JSON
    out = llm["json"]
    raw = json.loads(json.dumps(out, ensure_ascii=False))
    mismatch = bool(voice and voice.get("voice_down") and out["mood"] in rules.MISMATCH_MOODS)
    result = rules.postprocess(out, masked, hist, voice_mismatch=mismatch)

    if not (current := _current(db, job.user_id, reply_id)):
        return
    reply, row = current
    row.llm_raw, row.result, row.level, row.mood = raw, result, result["level"], result["mood"]
    row.voice_mismatch, row.reply_chars = result["voice_mismatch"], len(masked)
    row.prompt_id, row.llm_model = rules.PROMPT_ID, llm["model"]
    timings.update(llm=llm["seconds"], llm_attempts=llm["attempts"], prompt_tokens=llm["prompt_tokens"],
                   completion_tokens=llm["completion_tokens"])
    timings["total"] = round(time.monotonic() - started, 1)
    row.timings = timings
    _finish(row, "done")
    _notify(db, reply, result["level"])
    db.commit()
    log.info("답장 분석 #%s 끝 (%s, %.1f초, %s %.1f초, 시도 %s, 토큰 %s→%s)", reply.id, reply.kind, timings["total"],
             llm["model"], llm["seconds"], llm["attempts"], llm["prompt_tokens"], llm["completion_tokens"])


def on_final_failure(db: Session, job: Job) -> None:
    row = db.scalar(select(ReplyAnalysis).where(
        ReplyAnalysis.reply_id == (job.payload or {}).get("reply_id"), ReplyAnalysis.user_id == job.user_id,
    ))
    if row and row.status in ("queued", "running"):
        _finish(row, "failed", (job.last_error or "")[:300])
