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
from .services import audio, face, jobs, korean, s3gen, s3gen_remote, storage, tts, video, wemeet_tts, young

log = logging.getLogger("ongi.worker")

# TTS 서버 참조 음성: 차분한 문장 1개. 서버는 말소리 3초 이상을 요구하고 앞 10초만 쓴다.
# 10초보다 긴 대본은 _reference_file이 10초 안쪽의 쉼에서 잘라서 보낸다
MIN_GOOD_REFERENCE_SECONDS = 6.0
MIN_REFERENCE_SECONDS = 3.5  # 녹음 길이에는 앞뒤 여백 0.15초씩이 들어 있어서 서버 기준(3초)보다 조금 길게 잡는다


def _pick_reference(samples: list[VoiceSample], sentences: list[dict]) -> VoiceSample | None:
    """6초 이상인 것 → 차분한 문장 → 평서문 → 잡음이 적은 것 순으로 고른다. 긴 녹음은 잘라 쓰므로 길어도 깎지 않는다."""
    kinds = {i: s["kind"] for i, s in enumerate(sentences)}

    def rank(s: VoiceSample):
        short = max(MIN_GOOD_REFERENCE_SECONDS - s.duration, 0.0)
        kind = kinds.get(s.index)
        return (round(short, 1), kind != "calm", kind != "statement", -s.snr_db)

    usable = [s for s in samples if s.duration >= MIN_REFERENCE_SECONDS]
    return min(usable, key=rank) if usable else None


def _registered_reference(samples: list[VoiceSample], profile: VoiceProfile) -> VoiceSample | None:
    """TTS 서버에 등록한 참조 문장. 등록 뒤 음색 학습용으로 더 녹음해도 다른 문장으로 바뀌지 않게 저장한 번호를 쓴다.
    번호가 없는 예전 프로필은 지금처럼 고른다."""
    if profile.reference_index is not None:
        for s in samples:
            if s.index == profile.reference_index and s.duration >= MIN_REFERENCE_SECONDS:
                return s
    return _pick_reference(samples, profile.sentences)


def _reference_file(sample: VoiceSample) -> Path:
    """TTS 서버에 올리는 참조 음성. 10초보다 길면 10초 안쪽의 쉼에서 자른 파일을 만든다 (audio.trim_reference).
    음색 학습도 이 파일을 참조로 써서 실제로 등록된 목소리와 조건을 맞춘다."""
    path = storage.user_dir(sample.user_id, "voice") / "tts_reference.wav"
    audio.write_wav(path, audio.trim_reference(audio.read_wav(storage.abs_path(sample.path))))
    return path


def _register_voice(db: Session, profile: VoiceProfile, repick: bool = False) -> None:
    """녹음 중 참조 문장 1개를 골라 TTS 서버에 등록한다. 새로 등록할 때(repick)만 고르고,
    다시 올릴 때는 처음 등록한 문장을 그대로 쓴다 (붙여 둔 음색 어댑터가 그 문장 기준이라서).
    voice_id를 먼저 저장해 두므로, 등록하는 사이에 동의를 철회해도 삭제 작업이 이 id를 지운다."""
    samples = db.scalars(select(VoiceSample).where(VoiceSample.user_id == profile.user_id, VoiceSample.ok)).all()
    sample = _pick_reference(samples, profile.sentences) if repick else _registered_reference(samples, profile)
    if not sample:
        raise wemeet_tts.TTSRejected(
            f"참조 음성으로 쓸 {MIN_REFERENCE_SECONDS}초 이상 녹음이 없습니다.",
            user_message="목소리 녹음이 남아 있지 않아요. 처음부터 다시 녹음해 주세요.",
        )
    if not profile.tts_voice_id:
        profile.tts_voice_id = f"user_{profile.user_id}_{secrets.token_hex(4)}"
    profile.reference_index = sample.index
    profile.tts_registered_at = None
    db.commit()
    reference = _reference_file(sample)
    try:
        meta = wemeet_tts.register_voice(profile.tts_voice_id, reference)
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
        "TTS 목소리 등록 %s (문장 %s번, %.1f초 중 %.1f초, 말소리 %s초)",
        profile.tts_voice_id, sample.index, sample.duration, audio.wav_duration(reference), meta.get("speech_seconds"),
    )


def run_voice(db: Session, job: Job) -> None:
    """녹음 정리: 품질 좋은 문장으로 zero-shot용 참조 음성을 만들고, 전체 녹음을 학습용으로 이어 붙인다.
    TTS_PROVIDER=wemeet이면 참조 문장 1개를 TTS 서버에 등록하고, 사용자가 음색 학습을 골랐으면(payload tune) 학습 작업을 뒤에 넣는다.
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

    tune = bool((job.payload or {}).get("tune"))
    if settings.tts_provider == "wemeet":
        _register_voice(db, profile, repick=True)
        if tune:
            _queue_training(db, profile)

    profile.status = "ready"
    profile.error = None
    text = "목소리 등록이 끝났어요. 이제 영상을 만들 수 있어요."
    if profile.s3gen_status == "queued":
        text += " 목소리를 더 닮게 다듬는 동안에도 기본 목소리로 영상을 만들 수 있어요."
    db.add(Notification(user_id=job.user_id, kind="voice_ready", text=text))
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


def _young_photo(db: Session, photo: Photo) -> tuple[Path, list[int]]:
    """어린 시절 모드 사진과 얼굴 위치. 사용자당 한 번 만들어 두고 다음 영상부터 그대로 쓴다.
    COMFYUI_URL이 없으면 원본 사진을 쓴다 (GPU 없이 목소리 변환과 흐름만 확인할 때)."""
    if photo.young_path and photo.young_face:
        return storage.abs_path(photo.young_path), photo.young_face
    if not settings.comfyui_url:
        log.warning("COMFYUI_URL이 없어서 어린 시절 모드에 원본 사진을 씁니다.")
        return storage.abs_path(photo.path), photo.face
    data = young.generate(storage.abs_path(photo.path).read_bytes(), f"ongi_user_{photo.user_id}.jpg", settings.young_age)
    result = face.check(data)
    if not result.face:
        raise young.YoungPhotoError("어린 시절 사진에서 얼굴을 찾지 못했습니다.", retryable=False)
    # 만든 사진은 매끈해서 '흐림'에, 멀리서 찍은 구도라 '얼굴이 작음'에 걸릴 수 있다. 영상에는 얼굴 위치만 있으면 된다
    if result.problems:
        log.info("어린 시절 사진 검사 참고: %s", result.problems)
    path = storage.user_dir(photo.user_id, "photo") / "young.png"
    result.image.save(path)
    photo.young_path, photo.young_face = storage.rel_path(path), result.face
    db.commit()
    return path, result.face


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
    # 입 모양이 바뀐 목소리에 맞도록 영상(FLOAT)에 넣기 전에 바꾼다. 다시 돌 때는 TTS부터 새로 만들어서 두 번 바뀌지 않는다
    if m.young and settings.young_voice_pitch != 1:
        audio.make_younger(wav, settings.young_voice_pitch)

    job.stage = "video"
    job.video_provider = settings.video_provider
    db.commit()
    photo_path, face_box = _young_photo(db, photo) if m.young else (storage.abs_path(photo.path), photo.face)
    mp4, poster = out_dir / "video.mp4", out_dir / "poster.jpg"
    v = video.render(photo_path, face_box, wav, mp4, poster, emotion=m.emotion or video.DEFAULT_EMOTION)

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
    """등록할 때 음색 학습까지 고른 경우. 그사이 학습을 끌 수 없게 됐으면 기본 목소리로만 둔다 (나중에 다시 고를 수 있다)."""
    if not settings.s3gen_training:
        log.warning("S3GEN_TRAINING이 꺼져 있어서 음색 학습을 건너뜁니다.")
        return
    reason = s3gen.unavailable_reason()
    if reason:
        log.warning("S3Gen 음색 학습을 건너뜁니다: %s", reason)
        return
    jobs.enqueue_voice_train(db, profile)


# 음색 학습 결과 알림. 기본 목소리 유지·실패면 다시 학습할 수 있다고 알린다 (녹음 화면에서 고른다)
TUNE_APPLIED_TEXT = "목소리를 내 목소리에 더 닮게 다듬었어요. 이제부터 영상에 다듬은 목소리가 쓰여요."
TUNE_SKIPPED_TEXT = (
    "이번 음색 학습으로는 기본 목소리보다 더 닮게 만들지 못해서 기본 목소리를 그대로 쓰고 있어요. "
    "원하면 몇 문장 더 녹음하고 다시 학습해 볼 수 있어요."
)
TUNE_NOISY_TEXT = (
    "잡음이나 다른 소리가 섞인 녹음을 빼고 나니 음색 학습에 쓸 녹음이 모자라서 기본 목소리를 그대로 쓰고 있어요. "
    "원하면 조용한 곳에서 몇 문장 더 녹음하고 다시 학습해 볼 수 있어요."
)
TUNE_FAILED_TEXT = "목소리를 다듬다가 문제가 생겨서 기본 목소리를 그대로 쓰고 있어요. 원하면 다시 학습해 볼 수 있어요."


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
    ref = _registered_reference(samples, profile)  # TTS 서버에 등록한 문장
    if not ref:
        raise s3gen.TrainingError("참조 문장이 없습니다.", retryable=False)
    profile.s3gen_status = "training"
    db.commit()

    def still_current() -> bool:
        db.expire_all()
        return _train_target(db, job) is not None

    # 참조 문장은 TTS 서버에 등록한 것과 같은 잘린 파일을 쓴다 (학습 프롬프트·비교용 후보 목소리 모두)
    reference = _reference_file(ref)
    clips = [
        {"id": f"s{s.index:02d}", "audio": str(storage.abs_path(s.path)), "duration": round(s.duration, 2)}
        if s is not ref
        else {"id": f"s{s.index:02d}", "audio": str(reference), "duration": round(audio.wav_duration(reference), 2)}
        for s in samples
    ]
    # GPU가 없는 곳(Azure)에서는 GPU PC의 학습 서버에 맡긴다. 돌려받는 결과 형식은 같다
    runner = s3gen_remote.run if settings.s3gen_remote_url else s3gen.run
    try:
        outcome = runner(clips, f"s{ref.index:02d}", reference, voice_id, work, still_current)
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
    text = TUNE_APPLIED_TEXT if outcome.applied else TUNE_NOISY_TEXT if outcome.reason == "not_enough_audio" else TUNE_SKIPPED_TEXT
    db.add(Notification(user_id=job.user_id, kind="voice_tuned" if outcome.applied else "voice_tune_skipped", text=text))
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
        # 음색 학습이 끝내 실패해도 기본 목소리로 계속 쓴다. 사용자가 고른 학습이라 결과를 알리고 다시 학습할 수 있게 둔다
        voice_id = (job.payload or {}).get("voice_id")
        if voice_id:
            storage.delete_tree(_train_dir(job.user_id, voice_id))
        profile = _train_target(db, job)
        if profile:
            profile.s3gen_status = "failed"
            profile.s3gen_report = {"result": "failed", "error": (job.last_error or "")[:500], "finished_at": iso(utcnow())}
            db.add(Notification(user_id=job.user_id, kind="voice_tune_failed", text=TUNE_FAILED_TEXT))
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
    from .services.conversations import refresh_closed_portfolios

    last_check = time.monotonic()
    last_portfolio_check = 0.0
    while True:
        try:
            with SessionLocal() as db:
                if time.monotonic() - last_portfolio_check > 60:
                    last_portfolio_check = time.monotonic()
                    try:
                        changed = refresh_closed_portfolios(db)
                        if changed:
                            log.info("지난달 대화 포트폴리오 %s개 작성", changed)
                    except Exception:
                        db.rollback()
                        log.exception("대화 포트폴리오 자동 작성 오류")
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
