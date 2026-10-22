"""DB 기반 작업 큐.

웹 서버는 enqueue만 하고, 실제 처리는 별도 프로세스(app.worker)가 claim해서 한다.
Celery/Redis로 옮길 때는 enqueue에서 task.delay(job.id)를 부르고 워커가 claim 대신 job.id로 시작하면 된다.
"""

from datetime import timedelta

from sqlalchemy import case, select, update
from sqlalchemy.orm import Session

from ..config import settings
from ..db import utcnow
from ..models import Job

STALE_AFTER = timedelta(minutes=20)
# TTS 서버가 꺼져 있어도 목소리 삭제는 끝까지 해야 해서 오래 재시도한다 (10초부터 두 배씩, 약 1시간 반)
VOICE_DELETE_ATTEMPTS = 10


def enqueue(
    db: Session,
    type: str,
    user_id: int,
    message_id: int | None = None,
    payload: dict | None = None,
    replace: bool = True,
    max_attempts: int | None = None,
) -> Job:
    # 같은 대상에 대기 중인 작업이 있으면 취소하고 새로 넣는다 (다시 만들기).
    # 삭제 작업처럼 대상마다 따로 끝까지 실행돼야 하는 작업은 replace=False로 넣는다
    if replace:
        db.execute(
            update(Job)
            .where(Job.type == type, Job.user_id == user_id, Job.message_id == message_id, Job.status == "queued")
            .values(status="canceled", finished_at=utcnow())
        )
    job = Job(
        type=type,
        user_id=user_id,
        message_id=message_id,
        payload=payload,
        max_attempts=max_attempts or settings.job_max_attempts,
    )
    db.add(job)
    db.flush()
    return job


def enqueue_voice_delete(db: Session, user_id: int, voice_id: str) -> Job:
    """TTS 서버에 등록한 목소리 삭제. 다른 TTS 요청과 겹치지 않게 워커가 순서대로 처리한다."""
    return enqueue(
        db, "voice_delete", user_id, payload={"voice_id": voice_id}, replace=False, max_attempts=VOICE_DELETE_ATTEMPTS
    )


def enqueue_voice_train(db: Session, user_id: int, voice_id: str) -> Job:
    """S3Gen 음색 학습. 실패해도 기본 목소리로 계속 쓰므로 한 번만 다시 시도한다."""
    return enqueue(db, "voice_train", user_id, payload={"voice_id": voice_id}, max_attempts=2)


def claim(db: Session) -> Job | None:
    now = utcnow()
    # 음색 학습(약 5분)은 급하지 않으므로 대기 중인 영상 생성·등록·삭제를 먼저 처리한다
    candidates = db.scalars(
        select(Job.id)
        .where(Job.status == "queued", Job.run_after <= now)
        .order_by(case((Job.type == "voice_train", 1), else_=0), Job.id)
        .limit(5)
    ).all()
    for job_id in candidates:
        # 다른 워커가 먼저 가져갔으면 rowcount가 0
        result = db.execute(
            update(Job)
            .where(Job.id == job_id, Job.status == "queued")
            .values(status="running", started_at=now, attempts=Job.attempts + 1, stage=None)
        )
        db.commit()
        if result.rowcount == 1:
            return db.get(Job, job_id)
    return None


def finish(db: Session, job: Job) -> None:
    job.status = "done"
    job.stage = None
    job.finished_at = utcnow()
    db.commit()


def fail(db: Session, job: Job, error: str, retry: bool = True) -> bool:
    """재시도할 수 있으면 다시 대기열에 넣고 True, 최종 실패면 False.
    retry=False는 다시 해도 결과가 같은 오류(입력 문제 등)라서 남은 시도 횟수와 상관없이 바로 실패로 둔다."""
    job.last_error = error[:2000]
    if retry and job.attempts < job.max_attempts:
        job.status = "queued"
        job.run_after = utcnow() + timedelta(seconds=10 * 2 ** (job.attempts - 1))
        db.commit()
        return True
    job.status = "failed"
    job.finished_at = utcnow()
    db.commit()
    return False


def recover_stale(db: Session, older_than: timedelta = STALE_AFTER) -> int:
    """워커가 죽어서 running으로 남은 작업을 다시 대기열로 돌린다."""
    result = db.execute(
        update(Job)
        .where(Job.status == "running", Job.started_at <= utcnow() - older_than)
        .values(status="queued", run_after=utcnow())
    )
    db.commit()
    return result.rowcount


def running(db: Session, type: str) -> Job | None:
    """지금 워커가 처리 중인 그 종류의 작업 (워커가 1개라 많아야 1개)."""
    return db.scalars(select(Job).where(Job.type == type, Job.status == "running").limit(1)).first()


def latest(db: Session, type: str, user_id: int, message_id: int | None = None) -> Job | None:
    return db.scalars(
        select(Job)
        .where(Job.type == type, Job.user_id == user_id, Job.message_id == message_id, Job.status != "canceled")
        .order_by(Job.id.desc())
        .limit(1)
    ).first()
