"""GPU PC 음색 학습 서버: Azure 워커가 보낸 녹음으로 S3Gen 음색 어댑터를 학습한다 (services/s3gen.run 그대로).

Azure의 워커는 GPU가 없어서 학습을 직접 못 한다. 게이트웨이(gpu_worker/gateway.py)의 /train/* 로 이 서버를 부른다.
  POST   /jobs              녹음(clips, 파일 이름 = 녹음 id.wav)·참조 음성(reference)·meta(JSON) → {"job_id"}
  GET    /jobs/{id}         {"status": queued|running|done|failed|canceled, "outcome"|"error"}
  GET    /jobs/{id}/adapter 적용할 어댑터 파일 (outcome.applied일 때)
  DELETE /jobs/{id}         취소·정리 (받은 녹음과 중간 파일을 지운다)
  GET    /health            학습 가능 여부

학습 설정(S3GEN_STEPS·적용 기준·WEMEET_TRAIN_PYTHON 등)과 비교에 쓰는 TTS 서버는 이 PC의 backend/.env를 따른다.
한 번에 하나씩 돌린다 (GPU). 녹음 내용·문장은 로그에 남기지 않는다.
실행: npm run gpu가 같이 띄운다. 직접: python gpu_worker/trainer.py --port 8300
"""

import argparse
import json
import logging
import re
import secrets
import shutil
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import uvicorn  # noqa: E402
from fastapi import FastAPI, File, Form, HTTPException, UploadFile  # noqa: E402
from fastapi.responses import FileResponse  # noqa: E402

from app.config import settings  # noqa: E402
from app.services import s3gen  # noqa: E402

log = logging.getLogger("gpu_trainer")

ROOT = settings.data_dir / "remote_train"
VOICE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
CLIP_ID = re.compile(r"^s\d{1,3}$")
MAX_CLIPS, MAX_BYTES = 120, 200 * 1024 * 1024
KEEP_SECONDS = 6 * 3600  # 결과를 가져가지 않은 작업도 이만큼 지나면 지운다

app = FastAPI(title="GPU trainer", docs_url=None, redoc_url=None, openapi_url=None)
jobs: dict[str, dict] = {}
lock = threading.Lock()
executor = ThreadPoolExecutor(max_workers=1)  # GPU를 쓰므로 하나씩


def _cleanup_old() -> None:
    now = time.time()
    for job_id, job in list(jobs.items()):
        if job["status"] in ("done", "failed", "canceled") and now - job["updated"] > KEEP_SECONDS:
            shutil.rmtree(job["dir"], ignore_errors=True)
            jobs.pop(job_id, None)
    if ROOT.exists():  # 서버를 다시 띄워 기록이 없어진 작업 폴더
        for d in ROOT.iterdir():
            if d.name not in jobs and now - d.stat().st_mtime > KEEP_SECONDS:
                shutil.rmtree(d, ignore_errors=True)


def _set(job_id: str, **fields) -> None:
    with lock:
        jobs[job_id].update(fields, updated=time.time())


def _run_job(job_id: str) -> None:
    job = jobs[job_id]
    if job["canceled"]:
        _set(job_id, status="canceled")
        return
    _set(job_id, status="running")
    started = time.monotonic()
    try:
        outcome = s3gen.run(job["clips"], job["ref_id"], job["reference"], job["voice_id"], job["dir"] / "work",
                            still_current=lambda: not jobs[job_id]["canceled"])
        result = {"applied": outcome.applied, "reason": outcome.reason, "report": outcome.report,
                  "gpu_seconds": outcome.gpu_seconds}
        _set(job_id, status="canceled" if job["canceled"] else "done", outcome=result,
             adapter=str(outcome.adapter) if outcome.adapter else None)
        log.info("학습 %s 끝: %s (%.0f초)", job_id, outcome.reason, time.monotonic() - started)
    except s3gen.TrainingError as e:
        _set(job_id, status="failed", error=str(e)[-1500:], retryable=e.retryable)
        log.warning("학습 %s 실패: %s", job_id, str(e)[-300:])
    except Exception as e:  # noqa: BLE001 - 워커가 다시 시도하도록 실패로 돌려준다
        _set(job_id, status="failed", error=f"{type(e).__name__}: {e}"[-1500:], retryable=True)
        log.exception("학습 %s 오류", job_id)
    finally:
        # 비교용 임시 목소리는 이 PC의 TTS 서버에만 있으므로 여기서 지운다
        s3gen.delete_candidate(job["voice_id"])
        if job["canceled"]:  # 다시 녹음·동의 철회로 취소됐으면 받은 녹음을 바로 지운다
            shutil.rmtree(job["dir"], ignore_errors=True)
            with lock:
                jobs.pop(job_id, None)


@app.get("/health")
def health():
    reason = s3gen.unavailable_reason()
    running = sum(1 for j in jobs.values() if j["status"] in ("queued", "running"))
    return {"ok": reason is None, "reason": reason, "jobs_in_progress": running}


@app.post("/jobs")
async def create_job(meta: str = Form(...), reference: UploadFile = File(...), clips: list[UploadFile] = File(...)):
    reason = s3gen.unavailable_reason()
    if reason:
        raise HTTPException(503, reason)
    try:
        m = json.loads(meta)
        voice_id, ref_id, durations = m["voice_id"], m["ref_id"], {c["id"]: float(c["duration"]) for c in m["clips"]}
    except (ValueError, KeyError, TypeError):
        raise HTTPException(400, "meta 형식이 맞지 않습니다")
    if not VOICE_ID.match(voice_id) or not CLIP_ID.match(ref_id) or ref_id not in durations:
        raise HTTPException(400, "voice_id·ref_id가 맞지 않습니다")
    if not 0 < len(clips) <= MAX_CLIPS or len(clips) != len(durations):
        raise HTTPException(400, "녹음 수가 맞지 않습니다")
    _cleanup_old()

    job_id = secrets.token_hex(8)
    folder = ROOT / job_id
    (folder / "clips").mkdir(parents=True)
    total, saved = 0, []
    try:
        for f in clips:
            clip_id = Path(f.filename or "").stem
            if not CLIP_ID.match(clip_id) or clip_id not in durations:
                raise HTTPException(400, "녹음 파일 이름이 맞지 않습니다")
            data = await f.read()
            total += len(data)
            if total > MAX_BYTES:
                raise HTTPException(413, "녹음이 너무 큽니다")
            path = folder / "clips" / f"{clip_id}.wav"
            path.write_bytes(data)
            saved.append({"id": clip_id, "audio": str(path), "duration": durations[clip_id]})
        ref_path = folder / "reference.wav"
        ref_path.write_bytes(await reference.read())
    except HTTPException:
        shutil.rmtree(folder, ignore_errors=True)
        raise

    with lock:
        jobs[job_id] = {"status": "queued", "voice_id": voice_id, "ref_id": ref_id, "clips": saved,
                        "reference": ref_path, "dir": folder, "canceled": False, "updated": time.time()}
    executor.submit(_run_job, job_id)
    log.info("학습 %s 받음: 녹음 %d개 (%.0f초)", job_id, len(saved), sum(durations.values()))
    return {"job_id": job_id}


def _job(job_id: str) -> dict:
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "학습 작업이 없습니다 (학습 서버를 다시 띄웠을 수 있습니다)")
    return job


@app.get("/jobs/{job_id}")
def job_status(job_id: str):
    job = _job(job_id)
    out = {"status": job["status"]}
    if job["status"] == "done":
        out["outcome"] = job["outcome"]
    if job["status"] == "failed":
        out |= {"error": job["error"], "retryable": job["retryable"]}
    return out


@app.get("/jobs/{job_id}/adapter")
def job_adapter(job_id: str):
    job = _job(job_id)
    if job["status"] != "done" or not job.get("adapter") or not Path(job["adapter"]).exists():
        raise HTTPException(404, "적용할 어댑터가 없습니다")
    return FileResponse(job["adapter"], media_type="application/octet-stream")


@app.delete("/jobs/{job_id}")
def delete_job(job_id: str):
    job = jobs.get(job_id)
    if not job:
        return {"ok": True}
    if job["status"] in ("queued", "running"):
        # 학습 중이면 끝난 뒤(비교 전에) 멈추고, 정리는 그다음 요청이나 시간 지난 정리에서 한다
        _set(job_id, canceled=True)
        return {"ok": True, "status": "canceling"}
    shutil.rmtree(job["dir"], ignore_errors=True)
    jobs.pop(job_id, None)
    return {"ok": True}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")  # 게이트웨이를 거쳐서만 들어온다
    parser.add_argument("--port", type=int, default=8300)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    reason = s3gen.unavailable_reason()
    if reason:
        log.warning("지금은 학습을 할 수 없습니다: %s", reason)
    uvicorn.run(app, host=args.host, port=args.port, access_log=False)


if __name__ == "__main__":
    main()
