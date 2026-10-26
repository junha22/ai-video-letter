import secrets
from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import serialize
from ..auth import current_user
from ..config import settings
from ..db import get_db, utcnow
from ..models import Message, Photo, ShareLink, User, VoiceProfile
from ..services import jobs, script_llm, storage
from ..services import video as video_service  # 아래 video() 엔드포인트와 이름이 겹친다

router = APIRouter(prefix="/api/messages", tags=["messages"])

EDITABLE = ("draft", "ready", "failed")


def _get(db: Session, user: User, message_id: int) -> Message:
    m = db.get(Message, message_id)
    if not m or m.user_id != user.id or m.status == "deleted":
        raise HTTPException(404, "메시지를 찾을 수 없어요.")
    return m


def _clear_render(m: Message) -> None:
    for rel in (m.audio_path, m.video_path, m.poster_path):
        storage.delete_file(rel)
    m.audio_path = m.video_path = m.poster_path = None
    m.captions = None
    m.duration = None
    m.rendered_at = None


@router.get("")
def list_messages(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(
        select(Message).where(Message.user_id == user.id, Message.status != "deleted").order_by(Message.id.desc()).limit(50)
    ).all()
    return [serialize.message(db, m) for m in rows]


class MessageIn(BaseModel):
    memo: str = Field(min_length=1, max_length=200)
    template: str = "greeting"


@router.post("")
def create_message(body: MessageIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not serialize.consent_ok(db, user.id):
        raise HTTPException(403, "먼저 동의 화면을 완료해 주세요.")
    parent = user.parent
    if not parent:
        raise HTTPException(400, "먼저 부모님 정보를 등록해 주세요.")
    template = body.template if body.template in script_llm.TEMPLATES else "greeting"
    m = Message(user_id=user.id, parent_id=parent.id, memo=body.memo.strip(), template=template)
    m.parent = parent
    _fill_candidates(m)
    db.add(m)
    db.commit()
    return serialize.message(db, m)


def _fill_candidates(m: Message, level: str | None = None) -> None:
    """후보 대본을 새로 만든다. 후보가 하나뿐이면(AI 연결 실패 등) 고를 필요 없이 바로 쓴다.
    말투는 이번에 바꾼 값 > 이 메시지에 쓰던 값 > 부모님 정보·메모로 판단한 값 순서."""
    p = m.parent
    m.speech_level = level or m.speech_level or script_llm.speech_level(p.tone_examples, m.memo, p.speech_level)
    m.candidates = script_llm.generate_candidates(
        m.memo, m.template, p.nickname, p.relation, p.child_name, p.tone_examples, m.speech_level
    )
    m.chosen_style = None
    m.script = ""
    m.script_source = "llm"
    if len(m.candidates) == 1:
        _choose(m, m.candidates[0])


def _choose(m: Message, candidate: dict) -> None:
    m.chosen_style = candidate["style"]
    m.script = candidate["script"]
    m.script_source = candidate["source"]


@router.get("/{message_id}")
def get_message(message_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return serialize.message(db, _get(db, user, message_id))


class ScriptIn(BaseModel):
    script: str = Field(min_length=1, max_length=400)


@router.patch("/{message_id}")
def edit_script(message_id: int, body: ScriptIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    m = _get(db, user, message_id)
    if m.status not in EDITABLE:
        raise HTTPException(409, "이미 승인한 메시지는 고칠 수 없어요. 새 메시지를 만들어 주세요.")
    script = body.script.strip()
    if script != m.script:
        m.script = script
        m.script_source = "edited"
        _clear_render(m)
    m.status = "draft"
    db.commit()
    return serialize.message(db, m)


class ChooseIn(BaseModel):
    style: str = Field(max_length=20)


@router.post("/{message_id}/choose")
def choose_candidate(message_id: int, body: ChooseIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    m = _get(db, user, message_id)
    if m.status not in EDITABLE:
        raise HTTPException(409, "이미 승인한 메시지는 고칠 수 없어요.")
    candidate = next((c for c in m.candidates or [] if c["style"] == body.style), None)
    if not candidate:
        raise HTTPException(404, "대본 후보를 찾을 수 없어요.")
    if candidate["script"] != m.script:
        _clear_render(m)
    _choose(m, candidate)
    m.status = "draft"
    db.commit()
    return serialize.message(db, m)


class RewriteIn(BaseModel):
    # 후보 화면의 "존댓말로 바꾸기" 버튼. 없으면 쓰던 말투 그대로 새로 쓴다
    speech_level: Literal["반말", "존댓말"] | None = None


@router.post("/{message_id}/rewrite")
def rewrite_script(
    message_id: int, body: RewriteIn | None = None, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    m = _get(db, user, message_id)
    if m.status not in EDITABLE:
        raise HTTPException(409, "이미 승인한 메시지는 고칠 수 없어요.")
    _fill_candidates(m, body.speech_level if body else None)
    m.status = "draft"
    _clear_render(m)
    db.commit()
    return serialize.message(db, m)


class RenderIn(BaseModel):
    emotion: str = video_service.DEFAULT_EMOTION


@router.post("/{message_id}/render")
def render(
    message_id: int, body: RenderIn | None = None, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    m = _get(db, user, message_id)
    if m.status not in EDITABLE:
        raise HTTPException(409, "이미 승인한 메시지예요.")
    if not m.script:
        raise HTTPException(400, "대본 후보 중 하나를 먼저 골라 주세요.")
    emotion = body.emotion if body else video_service.DEFAULT_EMOTION
    if emotion not in video_service.EMOTIONS:
        raise HTTPException(400, "영상 표정을 다시 골라 주세요.")
    problems = script_llm.validate(m.script)
    if problems:
        raise HTTPException(400, " ".join(problems))
    if not serialize.consent_ok(db, user.id):
        raise HTTPException(403, "동의가 필요해요.")
    voice = db.scalar(select(VoiceProfile).where(VoiceProfile.user_id == user.id))
    if not voice or voice.status != "ready":
        raise HTTPException(400, "목소리 등록이 끝나야 영상을 만들 수 있어요.")
    if not db.scalar(select(Photo).where(Photo.user_id == user.id)):
        raise HTTPException(400, "얼굴 사진을 먼저 올려 주세요.")
    m.status = "generating"
    m.error = None
    m.voice_profile_id = voice.id
    m.emotion = emotion
    # 사용자가 누른 생성·다시 만들기는 새 seed로 만들고, 작업 자동 재시도는 저장된 seed로 같은 음성을 만든다
    m.tts_seed = None
    jobs.enqueue(db, "video", user.id, m.id)
    db.commit()
    return serialize.message(db, m)


def _file(rel: str | None, media_type: str, filename: str | None = None) -> FileResponse:
    """filename을 주면 브라우저가 재생하지 않고 그 이름으로 내려받는다."""
    if not rel or not storage.abs_path(rel).exists():
        raise HTTPException(404)
    return FileResponse(storage.abs_path(rel), media_type=media_type, filename=filename)


def _download_name(m: Message, ext: str) -> str:
    # 디버깅할 때 어떤 seed로 만든 결과인지 파일 이름으로 구분한다
    seed = f"-seed{m.tts_seed}" if m.tts_seed is not None else ""
    return f"message-{m.id}{seed}.{ext}"


@router.get("/{message_id}/video")
def video(message_id: int, download: bool = False, user: User = Depends(current_user), db: Session = Depends(get_db)):
    m = _get(db, user, message_id)
    return _file(m.video_path, "video/mp4", _download_name(m, "mp4") if download else None)


@router.get("/{message_id}/audio")
def audio(message_id: int, download: bool = False, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """TTS가 만든 음성(영상에 들어가기 전 WAV). 디버깅용"""
    m = _get(db, user, message_id)
    return _file(m.audio_path, "audio/wav", _download_name(m, "wav") if download else None)


@router.get("/{message_id}/poster")
def poster(message_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return _file(_get(db, user, message_id).poster_path, "image/jpeg")


@router.post("/{message_id}/approve")
def approve(message_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    m = _get(db, user, message_id)
    if m.status in ("approved", "sent", "viewed"):
        return serialize.message(db, m)
    if m.status != "ready":
        raise HTTPException(409, "미리보기 영상이 완성된 뒤에 승인할 수 있어요.")
    m.status = "approved"
    m.approved_at = utcnow()
    db.add(
        ShareLink(
            message_id=m.id,
            token=secrets.token_urlsafe(16),
            expires_at=utcnow() + timedelta(days=settings.share_link_days),
        )
    )
    db.commit()
    return serialize.message(db, m)


class SentIn(BaseModel):
    channel: str = Field(default="link", max_length=20)  # kakao | share | copy


@router.post("/{message_id}/sent")
def mark_sent(message_id: int, body: SentIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    m = _get(db, user, message_id)
    if m.status == "approved":
        m.status = "sent"
        m.sent_at = utcnow()
        db.commit()
    return serialize.message(db, m)
