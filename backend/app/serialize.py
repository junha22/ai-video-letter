"""API 응답 형태를 한곳에서 만든다."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import settings
from .db import iso, utcnow
from .models import Consent, Job, Message, ParentProfile, Photo, ShareLink, User, VoiceProfile, VoiceSample
from .services import jobs, s3gen, script_llm

CONSENT_VERSION = "2026-10"
CONSENT_ITEMS = [
    {
        "kind": "voice",
        "title": "내 목소리 사용 동의",
        "description": "녹음한 내 목소리로 음성 합성 모델을 만들고, 내가 승인한 영상 편지에만 사용합니다.",
    },
    {
        "kind": "face",
        "title": "내 얼굴 사진 사용 동의",
        "description": "올린 얼굴 사진으로 영상을 만들고, 내가 승인한 영상 편지에만 사용합니다.",
    },
    {
        "kind": "parent_receive",
        "title": "부모님 수신 동의 확인",
        "description": "부모님께 AI로 만든 영상 편지를 받는 것에 대해 동의를 받았습니다.",
    },
]


def active_consents(db: Session, user_id: int) -> dict[str, Consent]:
    rows = db.scalars(
        select(Consent).where(Consent.user_id == user_id, Consent.withdrawn_at.is_(None)).order_by(Consent.id)
    ).all()
    return {c.kind: c for c in rows}


def consent_ok(db: Session, user_id: int) -> bool:
    return all(item["kind"] in active_consents(db, user_id) for item in CONSENT_ITEMS)


def consent_state(db: Session, user_id: int) -> dict:
    active = active_consents(db, user_id)
    return {
        "version": CONSENT_VERSION,
        "ok": all(item["kind"] in active for item in CONSENT_ITEMS),
        "items": [{**item, "agreed_at": iso(active[item["kind"]].agreed_at) if item["kind"] in active else None} for item in CONSENT_ITEMS],
    }


def parent(p: ParentProfile | None) -> dict | None:
    if not p:
        return None
    return {
        "nickname": p.nickname,
        "relation": p.relation,
        "phone": p.phone,
        "child_call_name": p.child_call_name,
        "child_name": p.child_name,
        "speech_level": p.speech_level,
        "tone_examples": p.tone_examples,
    }


def voice_seconds(db: Session, user_id: int) -> float:
    total = db.scalar(select(func.sum(VoiceSample.duration)).where(VoiceSample.user_id == user_id, VoiceSample.ok))
    return round(total or 0.0, 1)


def job(j: Job | None) -> dict | None:
    if not j:
        return None
    return {
        "status": j.status,
        "stage": j.stage,
        "attempts": j.attempts,
        "max_attempts": j.max_attempts,
        "last_error": j.last_error,
        "tts_provider": j.tts_provider,
        "video_provider": j.video_provider,
        "gpu_seconds": round(j.gpu_seconds, 2),
        "cost_usd": j.cost_usd,
        "created_at": iso(j.created_at),
        "started_at": iso(j.started_at),
        "finished_at": iso(j.finished_at),
    }


def queue_wait(db: Session, j: Job | None, user_id: int) -> dict | None:
    """대기 중인 작업이 음색 학습 때문에 기다리는지. 워커가 1개라 학습(약 5분)이 끝나야 다음 작업을 시작한다.
    다른 사용자의 학습이면 누구 것인지 드러내지 않고 '앞선 작업'으로만 알린다."""
    if not j or j.status != "queued":
        return None
    train = jobs.running(db, "voice_train")
    if not train or not train.started_at:
        return None
    elapsed = (utcnow() - train.started_at).total_seconds()
    return {
        "reason": "own_voice_train" if train.user_id == user_id else "voice_train",
        "seconds": max(60, round(s3gen.EXPECTED_SECONDS - elapsed)),
    }


def voice_summary(db: Session, user_id: int) -> dict:
    profile = db.scalar(select(VoiceProfile).where(VoiceProfile.user_id == user_id))
    return {
        "status": profile.status if profile else "none",
        # S3Gen 음색 학습: queued | training | applied | skipped | failed | None(학습 안 함)
        "tuning": profile.s3gen_status if profile else None,
        "total_seconds": voice_seconds(db, user_id),
        "target_seconds": settings.voice_target_seconds,
        "error": profile.error if profile else None,
    }


def photo(p: Photo | None) -> dict | None:
    if not p:
        return None
    return {
        "width": p.width,
        "height": p.height,
        "face": p.face,
        "url": f"/api/photo/image?v={int(p.created_at.timestamp())}",
    }


def me(db: Session, user: User) -> dict:
    from .auth import user_info
    voice = voice_summary(db, user.id)
    p = db.scalar(select(Photo).where(Photo.user_id == user.id))
    consent = consent_ok(db, user.id)
    return {
        "user": user_info(db, user),
        "consent_ok": consent,
        "parent": parent(user.parent),
        "voice": voice,
        "photo": photo(p),
        "can_write": consent and user.parent is not None,
        "can_render": consent and voice["status"] == "ready" and p is not None,
    }


def share_url(token: str) -> str:
    return f"{settings.public_base_url}/w/{token}"


def message(db: Session, m: Message) -> dict:
    link = db.scalar(select(ShareLink).where(ShareLink.message_id == m.id))
    render_job = jobs.latest(db, "video", m.user_id, m.id)
    version = int(m.rendered_at.timestamp()) if m.rendered_at else 0
    has_video = bool(m.video_path) and m.status not in ("draft", "generating", "deleted")
    recipient = m.recipient or m.parent
    replies = (m.script_context or {}).get("replies", [])  # 대본을 만들 때 반영한 부모님 답글
    return {
        "id": m.id,
        "recipient_id": m.recipient_id,
        "recipient": {
            "id": m.recipient_id, "nickname": recipient.nickname, "relation": recipient.relation,
            "phone": recipient.phone, "child_name": recipient.child_name,
        } if recipient else None,
        "memo": m.memo,
        "template": m.template,
        "template_label": script_llm.TEMPLATES.get(m.template, ("안부",))[0],
        "candidates": [
            {
                **c,
                "char_count": script_llm.char_count(c["script"]),
                "est_seconds": script_llm.estimate_seconds(c["script"]),
                "warnings": script_llm.fact_warnings(c["script"], m.memo, replies) if c["source"] == "llm" else [],
                # 3번 다 고쳐 쓰지 못한 대본도 후보로 나오므로, 고르기 전에 그대로는 영상을 못 만든다는 걸 보여 준다
                "problems": script_llm.validate(c["script"]),
            }
            for c in m.candidates or []
        ],
        "chosen_style": m.chosen_style,
        "speech_level": m.speech_level,
        "script_context": m.script_context,
        "script": m.script,
        "script_source": m.script_source,
        "script_problems": script_llm.validate(m.script) if m.script else [],
        # 직접 고친 대본은 자녀가 일부러 넣은 것일 수 있어서 AI 대본에만 경고한다
        "script_warnings": script_llm.fact_warnings(m.script, m.memo, replies) if m.script_source == "llm" else [],
        "char_count": script_llm.char_count(m.script),
        "est_seconds": script_llm.estimate_seconds(m.script),
        "status": m.status,
        "error": m.error,
        "duration": m.duration,
        "captions": m.captions,
        "video_url": f"/api/messages/{m.id}/video?v={version}" if has_video else None,
        "poster_url": f"/api/messages/{m.id}/poster?v={version}" if has_video else None,
        "audio_url": f"/api/messages/{m.id}/audio?v={version}" if has_video and m.audio_path else None,
        "tts_seed": m.tts_seed,
        "emotion": m.emotion,
        "job": job(render_job),
        "wait": queue_wait(db, render_job, m.user_id) if m.status == "generating" else None,
        "share": {
            "url": share_url(link.token),
            "expires_at": iso(link.expires_at),
            "view_count": link.view_count,
            "first_viewed_at": iso(link.first_viewed_at),
        }
        if link and not link.revoked
        else None,
        "parent_nickname": recipient.nickname if recipient else None,
        "created_at": iso(m.created_at),
        "approved_at": iso(m.approved_at),
        "sent_at": iso(m.sent_at),
        "viewed_at": iso(m.viewed_at),
    }
