from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import serialize
from ..auth import current_user
from ..config import settings
from ..db import get_db, utcnow
from ..models import Job, User, VoiceProfile, VoiceSample
from ..services import audio, jobs, sentences, storage

router = APIRouter(prefix="/api/voice", tags=["voice"])

MAX_UPLOAD = 10 * 1024 * 1024


def _profile(db: Session, user: User) -> VoiceProfile:
    profile = db.scalar(select(VoiceProfile).where(VoiceProfile.user_id == user.id))
    if not profile:
        profile = VoiceProfile(user_id=user.id, sentences=sentences.assign())
        db.add(profile)
        try:
            db.commit()
        except IntegrityError:
            # 첫 요청이 동시에 두 번 들어오면(개발 모드에서 React가 effect를 두 번 실행할 때 등) 먼저 만든 쪽을 쓴다
            db.rollback()
            profile = db.scalar(select(VoiceProfile).where(VoiceProfile.user_id == user.id))
    return profile


def _state(db: Session, user: User, profile: VoiceProfile) -> dict:
    samples = {s.index: s for s in db.scalars(select(VoiceSample).where(VoiceSample.user_id == user.id))}
    return {
        "status": profile.status,
        "tuning": profile.s3gen_status,
        "tuning_report": profile.s3gen_report,  # 분할·학습·유사도 비교 결과 (디버깅용)
        "error": profile.error,
        "total_seconds": serialize.voice_seconds(db, user.id),
        "target_seconds": settings.voice_target_seconds,
        "sentences": [
            {
                "index": i,
                "text": s["text"],
                "kind": s["kind"],
                **sentences.guidance(s),
                "sample": {"duration": round(samples[i].duration, 1), "ok": samples[i].ok} if i in samples else None,
            }
            for i, s in enumerate(profile.sentences)
        ],
        "job": serialize.job(jobs.latest(db, "voice", user.id)),
    }


def _require_consent(db: Session, user: User) -> None:
    if "voice" not in serialize.active_consents(db, user.id):
        raise HTTPException(403, "목소리 사용 동의가 필요해요.")


@router.get("")
def get_voice(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return _state(db, user, _profile(db, user))


@router.post("/samples/{index}")
def upload_sample(index: int, file: UploadFile = File(...), user: User = Depends(current_user), db: Session = Depends(get_db)):
    _require_consent(db, user)
    profile = _profile(db, user)
    if profile.status not in ("recording", "failed"):
        raise HTTPException(409, "이미 목소리 등록이 끝났어요. 다시 녹음하려면 처음부터 다시 시작해 주세요.")
    if not 0 <= index < len(profile.sentences):
        raise HTTPException(404, "문장을 찾을 수 없어요.")
    data = file.file.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "녹음 파일이 너무 커요.")
    try:
        samples = audio.decode(data)
    except RuntimeError:
        raise HTTPException(400, "녹음 파일을 읽을 수 없어요. 다시 녹음해 주세요.")

    quality = audio.analyze(samples)
    if quality.ok:
        path = storage.user_dir(user.id, "voice") / f"sample_{index:02d}.wav"
        cleaned = audio.clean(samples)
        audio.write_wav(path, cleaned)
        sample = db.scalar(select(VoiceSample).where(VoiceSample.user_id == user.id, VoiceSample.index == index))
        sample = sample or VoiceSample(user_id=user.id, index=index)
        sample.text = profile.sentences[index]["text"]
        sample.path = storage.rel_path(path)
        sample.duration = len(cleaned) / audio.SAMPLE_RATE
        sample.speech_db = quality.speech_db
        sample.snr_db = quality.snr_db
        sample.ok = True
        db.add(sample)
        db.commit()
    return {
        "ok": quality.ok,
        "problems": quality.problems,
        "metrics": {
            "duration": round(quality.duration, 1),
            "speech_db": quality.speech_db,
            "snr_db": quality.snr_db,
            "clip_ratio": quality.clip_ratio,
        },
        "total_seconds": serialize.voice_seconds(db, user.id),
    }


@router.post("/finalize")
def finalize(user: User = Depends(current_user), db: Session = Depends(get_db)):
    _require_consent(db, user)
    profile = _profile(db, user)
    if profile.status in ("processing", "ready"):
        return _state(db, user, profile)
    total = serialize.voice_seconds(db, user.id)
    if total < settings.voice_target_seconds:
        raise HTTPException(400, f"녹음이 {settings.voice_target_seconds - total:.0f}초 더 필요해요.")
    profile.status = "processing"
    profile.error = None
    jobs.enqueue(db, "voice", user.id)
    db.commit()
    return _state(db, user, profile)


@router.post("/reset")
def reset(user: User = Depends(current_user), db: Session = Depends(get_db)):
    storage.delete_tree(storage.user_dir(user.id, "voice"))
    db.execute(delete(VoiceSample).where(VoiceSample.user_id == user.id))
    profile = _profile(db, user)
    if profile.tts_voice_id:
        # 새로 녹음하면 새 voice_id로 등록하므로, 예전 목소리 삭제가 늦게 실행돼도 새 목소리를 지우지 않는다.
        # TTS 서버는 목소리 폴더째 지우므로 붙여 둔 음색 어댑터도 같이 지워진다
        jobs.enqueue_voice_delete(db, user.id, profile.tts_voice_id)
    # 대기 중인 음색 학습은 취소한다. 이미 학습 중이면 끝난 뒤 목소리가 바뀐 것을 보고 결과를 버린다
    db.execute(
        update(Job)
        .where(Job.user_id == user.id, Job.type == "voice_train", Job.status == "queued")
        .values(status="canceled", finished_at=utcnow())
    )
    profile.tts_voice_id = None
    profile.tts_registered_at = None
    profile.s3gen_status = None
    profile.s3gen_adapter_path = None
    profile.s3gen_report = None
    profile.status = "recording"
    profile.error = None
    profile.reference_path = None
    profile.sentences = sentences.assign()
    db.commit()
    return _state(db, user, profile)
