"""DB 기반 작업 큐.

웹 서버는 enqueue만 하고, 실제 처리는 별도 프로세스(app.worker)가 claim해서 한다.
Celery/Redis로 옮길 때는 enqueue에서 task.delay(job.id)를 부르고 워커가 claim 대신 job.id로 시작하면 된다.
"""

from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..config import settings
from ..db import utcnow
from ..models import Job

STALE_AFTER = timedelta(minutes=20)


def enqueue(db: Session, type: str, user_id: int, message_id: int | None = None) -> Job:
    # 같은 대상에 대기 중인 작업이 있으면 취소하고 새로 넣는다 (다시 만들기)
    db.execute(
        update(Job)
        .where(Job.type == type, Job.user_id == user_id, Job.message_id == message_id, Job.status == "queued")
        .values(status="canceled", finished_at=utcnow())
    )
    job = Job(type=type, user_id=user_id, message_id=message_id, max_attempts=settings.job_max_attempts)
    db.add(job)
    db.flush()
    return job


def claim(db: Session) -> Job | None:
    now = utcnow()
    candidates = db.scalars(
        select(Job.id).where(Job.status == "queued", Job.run_after <= now).order_by(Job.id).limit(5)
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


def fail(db: Session, job: Job, error: str) -> bool:
    """재시도할 수 있으면 다시 대기열에 넣고 True, 최종 실패면 False."""
    job.last_error = error[:2000]
    if job.attempts < job.max_attempts:
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


def latest(db: Session, type: str, user_id: int, message_id: int | None = None) -> Job | None:
    return db.scalars(
        select(Job)
        .where(Job.type == type, Job.user_id == user_id, Job.message_id == message_id, Job.status != "canceled")
        .order_by(Job.id.desc())
        .limit(1)
    ).first()
