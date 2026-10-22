"""작업 큐 워커. 웹 서버와 별도 프로세스로 실행한다: python -m app.worker

TTS 서버(TTS_PROVIDER=wemeet)는 GPU 1장으로 요청을 하나씩 처리한다. 이 워커가 작업을 하나씩 처리하므로
목소리 등록·음성 생성·목소리 삭제·음색 학습이 서버와 GPU에 순서대로 전달된다. 워커는 1개만 띄운다.
"""

import logging
import secrets
import shutil
import time
import traceback
from datetime import timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import SessionLocal, init_db, iso, utcnow
from .models import Job, Message, Notification, Photo, VoiceProfile, VoiceSample
from .services import audio, jobs, korean, s3gen, storage, tts, video, wemeet_tts

log = logging.getLogger("ongi.worker")

# TTS 서버 참조 음성: 차분한 6~10초 문장 1개. 서버는 말소리 3초 이상을 요구하고 앞 10초만 쓴다
REFERENCE_SECONDS = (6.0, 10.0)
MIN_REFERENCE_SECONDS = 3.5  # 녹음 길이에는 앞뒤 여백 0.15초씩이 들어 있어서 서버 기준(3초)보다 조금 길게 잡는다


def _pick_reference(samples: list[VoiceSample], sentences: list[dict]) -> VoiceSample | None:
    """길이가 6~10초에 가까운 것 → 차분한 문장 → 평서문 → 잡음이 적은 것 순으로 고른다."""
    kinds = {i: s["kind"] for i, s in enumerate(sentences)}

    def rank(s: VoiceSample):
        off = max(REFERENCE_SECONDS[0] - s.duration, s.duration - REFERENCE_SECONDS[1], 0.0)
        kind = kinds.get(s.index)
        return (round(off, 1), kind != "calm", kind != "statement", -s.snr_db)

    usable = [s for s in samples if s.duration >= MIN_REFERENCE_SECONDS]
    return min(usable, key=rank) if usable else None


def _register_voice(db: Session, profile: VoiceProfile) -> None:
    """녹음 중 참조 문장 1개를 골라 TTS 서버에 등록한다.
    voice_id를 먼저 저장해 두므로, 등록하는 사이에 동의를 철회해도 삭제 작업이 이 id를 지운다."""
    samples = db.scalars(select(VoiceSample).where(VoiceSample.user_id == profile.user_id, VoiceSample.ok)).all()
    sample = _pick_reference(samples, profile.sentences)
    if not sample:
        raise wemeet_tts.TTSRejected(
            f"참조 음성으로 쓸 {MIN_REFERENCE_SECONDS}초 이상 녹음이 없습니다.",
            user_message="목소리 녹음이 남아 있지 않아요. 처음부터 다시 녹음해 주세요.",
        )
    if not profile.tts_voice_id:
        profile.tts_voice_id = f"user_{profile.user_id}_{secrets.token_hex(4)}"
    profile.tts_registered_at = None
    db.commit()
    try:
        meta = wemeet_tts.register_voice(profile.tts_voice_id, storage.abs_path(sample.path))
    except wemeet_tts.TTSRejected as e:
        if e.status == 400:  # 말소리가 너무 짧거나 없음
            e.user_message = "녹음에서 목소리를 읽지 못했어요. 처음부터 다시 녹음해 주세요."
        raise
    if profile.s3gen_adapter_path:
        # TTS 서버를 옮기거나 초기화해서 다시 등록하는 경우, 적용해 둔 음색 어댑터도 다시 붙인다
        adapter = storage.abs_path(profile.s3gen_adapter_path)
        if adapter.exists():
            wemeet_tts.set_s3gen_adapter(profile.tts_voice_id, adapter)
        else:
            log.warning("음색 어댑터 파일이 없어서 기본 목소리로 등록합니다 (%s)", profile.tts_voice_id)
            profile.s3gen_adapter_path = None
            profile.s3gen_status = "failed"
    profile.tts_registered_at = utcnow()
    db.commit()
    log.info(
        "TTS 목소리 등록 %s (문장 %s번, %.1f초, 말소리 %s초)",
        profile.tts_voice_id, sample.index, sample.duration, meta.get("speech_seconds"),
    )


def run_voice(db: Session, job: Job) -> None:
    """녹음 정리: 품질 좋은 문장으로 zero-shot용 참조 음성을 만들고, 전체 녹음을 학습용으로 이어 붙인다.
    TTS_PROVIDER=wemeet이면 참조 문장 1개를 TTS 서버에 등록하고, S3GEN_TRAINING이면 음색 학습 작업을 뒤에 넣는다.
    등록이 끝나면 바로 zero-shot으로 영상을 만들 수 있다."""
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
    profile.reference_path = storage.rel_path(reference)

    if settings.tts_provider == "wemeet":
        _register_voice(db, profile)
        _queue_training(db, profile)

    profile.status = "ready"
    profile.error = None
    db.add(Notification(user_id=job.user_id, kind="voice_ready", text="목소리 등록이 끝났어요. 이제 영상을 만들 수 있어요."))
    db.commit()


def _synthesize(db: Session, m: Message, profile: VoiceProfile, wav) -> tts.TTSResult:
    reference = storage.abs_path(profile.reference_path)
    if settings.tts_provider != "wemeet":
        return tts.synthesize(m.script, reference, wav)
    if not profile.tts_registered_at:
        # wemeet로 바꾸기 전에 등록을 마친 목소리는 여기서 처음 TTS 서버에 올린다
        _register_voice(db, profile)
    try:
        return tts.synthesize(m.script, reference, wav, voice_id=profile.tts_voice_id, seed=m.tts_seed)
    except wemeet_tts.VoiceNotFound:
        # TTS 서버를 옮기거나 초기화해서 목소리가 없어졌으면 남아 있는 녹음으로 다시 등록하고 한 번 더 만든다
        log.warning("TTS 서버에 목소리 %s가 없어서 다시 등록합니다.", profile.tts_voice_id)
        _register_voice(db, profile)
        return tts.synthesize(m.script, reference, wav, voice_id=profile.tts_voice_id, seed=m.tts_seed)


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
    t = _synthesize(db, m, profile, wav)
    # 영상 단계에서 실패해 작업이 다시 돌 때 같은 음성이 나오도록 seed를 바로 저장한다
    m.tts_seed = t.seed
    db.commit()

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


def run_voice_delete(db: Session, job: Job) -> None:
    """TTS 서버에 저장된 참조 음성 삭제 (동의 철회, 다시 녹음). 이미 없으면 그대로 끝낸다."""
    voice_id = (job.payload or {}).get("voice_id")
    if voice_id and not wemeet_tts.delete_voice(voice_id):
        log.info("TTS 목소리 %s는 이미 없습니다.", voice_id)


def _queue_training(db: Session, profile: VoiceProfile) -> None:
    if not settings.s3gen_training:
        return
    reason = s3gen.unavailable_reason()
    if reason:
        log.warning("S3Gen 음색 학습을 건너뜁니다: %s", reason)
        return
    jobs.enqueue_voice_train(db, profile.user_id, profile.tts_voice_id)
    profile.s3gen_status = "queued"
    profile.s3gen_adapter_path = None
    profile.s3gen_report = None


def _train_dir(user_id: int, voice_id: str) -> Path:
    # voice_id를 폴더 이름에 넣어서, 다시 녹음한 뒤 늦게 끝난 예전 학습이 새 녹음 폴더를 건드리지 않게 한다
    return storage.abs_path(f"users/{user_id}/voice/s3gen_work_{voice_id}")


def _train_target(db: Session, job: Job) -> VoiceProfile | None:
    """학습을 시작한 목소리가 아직 그대로인지 확인한다. 다시 녹음했거나 동의를 철회했으면 None."""
    voice_id = (job.payload or {}).get("voice_id")
    profile = db.scalar(select(VoiceProfile).where(VoiceProfile.user_id == job.user_id))
    if not profile or not voice_id or profile.tts_voice_id != voice_id or profile.status != "ready":
        return None
    return profile


def run_voice_train(db: Session, job: Job) -> None:
    """녹음으로 S3Gen 음색 어댑터를 학습해서, 기본 목소리보다 닮았을 때만 TTS 서버 목소리에 붙인다 (services/s3gen.py).
    학습하는 동안과 결과가 나쁠 때도 영상은 기본 목소리(zero-shot)로 만든다."""
    voice_id = (job.payload or {}).get("voice_id")
    work = _train_dir(job.user_id, voice_id)
    profile = _train_target(db, job)
    if not profile:
        storage.delete_tree(work)
        return
    if not settings.s3gen_training:  # 작업을 넣은 뒤 학습을 껐으면 기본 목소리로 둔다
        profile.s3gen_status = None
        db.commit()
        return
    reason = s3gen.unavailable_reason()
    if reason:
        raise s3gen.TrainingError(reason, retryable=False)
    samples = db.scalars(select(VoiceSample).where(VoiceSample.user_id == job.user_id, VoiceSample.ok)).all()
    ref = _pick_reference(samples, profile.sentences)  # TTS 서버에 등록한 문장과 같은 것이 골라진다
    if not ref:
        raise s3gen.TrainingError("참조 문장이 없습니다.", retryable=False)
    profile.s3gen_status = "training"
    db.commit()

    def still_current() -> bool:
        db.expire_all()
        return _train_target(db, job) is not None

    clips = [{"id": f"s{s.index:02d}", "audio": str(storage.abs_path(s.path)), "duration": round(s.duration, 2)} for s in samples]
    try:
        outcome = s3gen.run(clips, f"s{ref.index:02d}", storage.abs_path(ref.path), voice_id, work, still_current)
    finally:
        if not s3gen.delete_candidate(voice_id):
            jobs.enqueue_voice_delete(db, job.user_id, f"{voice_id}_cand")
            db.commit()
    job.gpu_seconds = outcome.gpu_seconds
    db.commit()

    # 학습하는 몇 분 사이에 다시 녹음하거나 동의를 철회했으면 결과를 버린다 (예전 목소리 삭제 작업은 이미 들어가 있다)
    db.expire_all()
    profile = _train_target(db, job)
    if not profile:
        storage.delete_tree(work)
        return
    if outcome.applied:
        wemeet_tts.set_s3gen_adapter(voice_id, outcome.adapter)
        adapter = storage.user_dir(job.user_id, "voice") / "s3gen_adapter.safetensors"
        shutil.copyfile(outcome.adapter, adapter)
        profile.s3gen_adapter_path = storage.rel_path(adapter)
    profile.s3gen_status = "applied" if outcome.applied else "skipped"
    profile.s3gen_report = {**outcome.report, "result": outcome.reason, "finished_at": iso(utcnow())}
    db.commit()
    storage.delete_tree(work)  # 특징값·비교 음성 같은 중간 파일은 남기지 않는다
    score = outcome.report.get("score", {})
    log.info(
        "S3Gen 음색 학습 %s: %s (유사도 변화 VoiceEncoder %s, WavLM %s)",
        voice_id, outcome.reason, score.get("gain", {}).get("ve"), score.get("gain", {}).get("sv"),
    )


HANDLERS = {"voice": run_voice, "video": run_video, "voice_delete": run_voice_delete, "voice_train": run_voice_train}


def _on_final_failure(db: Session, job: Job, user_message: str | None = None) -> None:
    if job.type == "video" and job.message_id:
        m = db.get(Message, job.message_id)
        if m and m.status == "generating":
            m.status = "failed"
            m.error = user_message or "영상을 만들지 못했어요. 잠시 뒤 다시 시도해 주세요."
    elif job.type == "voice":
        text = user_message or "목소리 등록에 실패했어요. 다시 시도해 주세요."
        profile = db.scalar(select(VoiceProfile).where(VoiceProfile.user_id == job.user_id))
        if profile:
            profile.status = "failed"
            profile.error = text
        db.add(Notification(user_id=job.user_id, kind="voice_failed", text=text))
    elif job.type == "voice_delete":
        log.error("TTS 목소리 %s를 지우지 못했습니다. TTS 서버에서 직접 지워야 합니다 (작업 #%s).", (job.payload or {}).get("voice_id"), job.id)
    elif job.type == "voice_train":
        # 음색 학습이 끝내 실패해도 기본 목소리로 계속 쓰므로 사용자에게 알리지 않는다
        voice_id = (job.payload or {}).get("voice_id")
        if voice_id:
            storage.delete_tree(_train_dir(job.user_id, voice_id))
        profile = _train_target(db, job)
        if profile:
            profile.s3gen_status = "failed"
            profile.s3gen_report = {"result": "failed", "error": (job.last_error or "")[:500], "finished_at": iso(utcnow())}
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
        # TTS 서버가 입력을 거절한 경우(400·404 등)는 다시 해도 같으므로 바로 실패로 둔다
        if not jobs.fail(db, job, f"{type(e).__name__}: {e}", retry=getattr(e, "retryable", True)):
            _on_final_failure(db, job, getattr(e, "user_message", None))
        return
    jobs.finish(db, job)
    log.info("작업 완료 #%s (%.1f초, GPU %.1f초, $%.4f)", job.id, time.monotonic() - started, job.gpu_seconds, job.cost_usd)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    init_db()
    with SessionLocal() as db:
        recovered = jobs.recover_stale(db, older_than=timedelta(0))
    log.info("워커 시작 (TTS=%s, 영상=%s, 복구한 작업 %s개)", settings.tts_provider, settings.video_provider, recovered)
    if settings.tts_provider == "wemeet":
        if wemeet_tts.health():
            log.info("TTS 서버 연결됨 (%s)", settings.wemeet_tts_url)
        else:
            log.warning(
                "TTS 서버(%s)에 연결할 수 없습니다. 먼저 띄우세요: "
                "powershell -ExecutionPolicy Bypass -File C:\\WE_MEET\\tts_server\\run_server.ps1",
                settings.wemeet_tts_url,
            )
        if settings.s3gen_training:
            reason = s3gen.unavailable_reason()
            if reason:
                log.warning("S3GEN_TRAINING이 켜져 있지만 학습할 수 없습니다: %s", reason)
            else:
                log.info("S3Gen 음색 학습 켜짐 (%s step, 배치 %s)", settings.s3gen_steps, settings.s3gen_batch_size)
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
