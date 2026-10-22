"""작업 큐 워커. 웹 서버와 별도 프로세스로 실행한다: python -m app.worker"""

import logging
import time
import traceback
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import SessionLocal, init_db, utcnow
from .models import Job, Message, Notification, Photo, VoiceProfile, VoiceSample
from .services import audio, jobs, korean, storage, tts, video

log = logging.getLogger("ongi.worker")


def run_voice(db: Session, job: Job) -> None:
    """녹음 정리: 품질 좋은 문장으로 zero-shot용 참조 음성을 만들고, 전체 녹음을 학습용으로 이어 붙인다.
    S3Gen 사용자별 학습은 이 단계 뒤에 붙인다 (MVP에서는 zero-shot으로 생성)."""
    profile = db.scalar(select(VoiceProfile).where(VoiceProfile.user_id == job.user_id))
    if not profile:
        return
    samples = db.scalars(select(VoiceSample).where(VoiceSample.user_id == job.user_id, VoiceSample.ok)).all()
    if not samples:
        raise RuntimeError("등록된 녹음이 없습니다.")
    voice_dir = storage.user_dir(job.user_id, "voice")

    picked, total = [], 0.0
    for s in sorted(samples, key=lambda s: s.snr_db, reverse=True):
        picked.append(storage.abs_path(s.path))
        total += s.duration
        if total >= settings.reference_seconds:
            break
    reference = voice_dir / "reference.wav"
    audio.write_wav(reference, audio.concat(picked))
    audio.write_wav(voice_dir / "all.wav", audio.concat([storage.abs_path(s.path) for s in sorted(samples, key=lambda s: s.index)]))

    profile.status = "ready"
    profile.error = None
    profile.reference_path = storage.rel_path(reference)
    db.add(Notification(user_id=job.user_id, kind="voice_ready", text="목소리 등록이 끝났어요. 이제 영상을 만들 수 있어요."))
    db.commit()


def run_video(db: Session, job: Job) -> None:
    m = db.get(Message, job.message_id)
    if not m or m.status != "generating":
        return
    profile = db.scalar(select(VoiceProfile).where(VoiceProfile.user_id == m.user_id))
    photo = db.scalar(select(Photo).where(Photo.user_id == m.user_id))
    if not profile or not profile.reference_path or not photo:
        raise RuntimeError("목소리나 사진이 등록되어 있지 않습니다.")
    out_dir = storage.message_dir(m.user_id, m.id)

    job.stage = "tts"
    job.tts_provider = settings.tts_provider
    db.commit()
    wav = out_dir / "audio.wav"
    t = tts.synthesize(korean.numbers_to_hangul(m.script), storage.abs_path(profile.reference_path), wav)

    job.stage = "video"
    job.video_provider = settings.video_provider
    db.commit()
    mp4, poster = out_dir / "video.mp4", out_dir / "poster.jpg"
    v = video.render(storage.abs_path(photo.path), photo.face, wav, mp4, poster)

    job.gpu_seconds = t.gpu_seconds + v.gpu_seconds
    job.cost_usd = round(t.cost_usd + v.cost_usd, 6)
    m.audio_path = storage.rel_path(wav)
    m.video_path = storage.rel_path(mp4)
    m.poster_path = storage.rel_path(poster)
    m.duration = v.duration
    m.captions = korean.make_captions(m.script, v.duration, tail=video.TAIL_SECONDS)
    m.rendered_at = utcnow()
    m.status = "ready"
    db.commit()


HANDLERS = {"voice": run_voice, "video": run_video}


def _on_final_failure(db: Session, job: Job) -> None:
    if job.type == "video" and job.message_id:
        m = db.get(Message, job.message_id)
        if m and m.status == "generating":
            m.status = "failed"
            m.error = "영상을 만들지 못했어요. 잠시 뒤 다시 시도해 주세요."
    elif job.type == "voice":
        profile = db.scalar(select(VoiceProfile).where(VoiceProfile.user_id == job.user_id))
        if profile:
            profile.status = "failed"
            profile.error = "목소리 등록에 실패했어요. 다시 시도해 주세요."
        db.add(Notification(user_id=job.user_id, kind="voice_failed", text="목소리 등록에 실패했어요. 다시 시도해 주세요."))
    db.commit()


def process(db: Session, job: Job) -> None:
    started = time.monotonic()
    log.info("작업 시작 #%s %s (시도 %s/%s)", job.id, job.type, job.attempts, job.max_attempts)
    try:
        HANDLERS[job.type](db, job)
    except Exception as e:
        db.rollback()
        job = db.get(Job, job.id)
        log.error("작업 실패 #%s: %s\n%s", job.id, e, traceback.format_exc())
        if not jobs.fail(db, job, f"{type(e).__name__}: {e}"):
            _on_final_failure(db, job)
        return
    jobs.finish(db, job)
    log.info("작업 완료 #%s (%.1f초, GPU %.1f초, $%.4f)", job.id, time.monotonic() - started, job.gpu_seconds, job.cost_usd)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    init_db()
    with SessionLocal() as db:
        recovered = jobs.recover_stale(db, older_than=timedelta(0))
    log.info("워커 시작 (TTS=%s, 영상=%s, 복구한 작업 %s개)", settings.tts_provider, settings.video_provider, recovered)
    last_check = time.monotonic()
    while True:
        try:
            with SessionLocal() as db:
                job = jobs.claim(db)
                if job:
                    process(db, job)
                    continue
                if time.monotonic() - last_check > 60:
                    jobs.recover_stale(db)
                    last_check = time.monotonic()
        except KeyboardInterrupt:
            raise
        except Exception:
            log.exception("워커 루프 오류")
        time.sleep(1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("워커 종료")
