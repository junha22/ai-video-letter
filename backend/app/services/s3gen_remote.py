"""S3Gen 음색 학습을 GPU PC의 학습 서버(gpu_worker/trainer.py)에 맡긴다 (S3GEN_REMOTE_URL이 있을 때).

Azure의 워커는 GPU가 없어서 s3gen.run을 직접 못 돌린다. 녹음과 참조 음성을 학습 서버에 보내고,
끝날 때까지 상태를 확인한 뒤 적용할 어댑터만 받아 온다. 돌려주는 값은 s3gen.run과 같아서 워커는 그대로 쓴다.
기다리는 동안 다시 녹음·동의 철회로 목소리가 바뀌면 학습 서버에 취소를 보낸다.
"""

import json
import time
from collections.abc import Callable
from contextlib import ExitStack
from pathlib import Path

import httpx

from ..config import log, settings
from .s3gen import Outcome, TrainingError

POLL_SECONDS = 10
DEADLINE_SECONDS = 3600  # 학습(배치 4 × 1000 step)은 보통 5~8분. GPU를 다른 작업과 나눠 쓰면 더 걸린다


def _client(timeout: float) -> httpx.Client:
    return httpx.Client(base_url=settings.s3gen_remote_url, headers={"X-API-Key": settings.s3gen_remote_key},
                        timeout=httpx.Timeout(timeout, connect=10))


def _cancel(job_id: str) -> None:
    try:
        with _client(30) as c:
            c.delete(f"/jobs/{job_id}")
    except httpx.HTTPError as e:
        log.warning("학습 서버 작업 %s를 정리하지 못했습니다: %s", job_id, type(e).__name__)


def run(
    clips: list[dict], ref_id: str, reference_wav: Path, voice_id: str, work: Path, still_current: Callable[[], bool]
) -> Outcome:
    meta = {"voice_id": voice_id, "ref_id": ref_id, "clips": [{"id": c["id"], "duration": c["duration"]} for c in clips]}
    try:
        with ExitStack() as stack, _client(300) as c:
            files = [("clips", (f"{x['id']}.wav", stack.enter_context(open(x["audio"], "rb")), "audio/wav")) for x in clips]
            files.append(("reference", ("reference.wav", stack.enter_context(open(reference_wav, "rb")), "audio/wav")))
            resp = c.post("/jobs", data={"meta": json.dumps(meta)}, files=files)
    except httpx.HTTPError as e:
        raise TrainingError(f"GPU PC 학습 서버에 연결하지 못했습니다: {type(e).__name__}") from e
    if resp.status_code != 200:
        raise TrainingError(f"학습 서버가 거절했습니다 ({resp.status_code}): {resp.text[:300]}",
                            retryable=resp.status_code >= 500)
    job_id = resp.json()["job_id"]
    log.info("S3Gen 학습을 GPU PC에 맡겼습니다 (작업 %s, 녹음 %d개)", job_id, len(clips))

    deadline = time.monotonic() + DEADLINE_SECONDS
    try:
        while True:
            time.sleep(POLL_SECONDS)
            if not still_current():
                _cancel(job_id)
                return Outcome(False, "voice_changed", {})
            if time.monotonic() > deadline:
                raise TrainingError(f"GPU PC 학습이 {DEADLINE_SECONDS // 60}분 안에 끝나지 않았습니다")
            try:
                with _client(30) as c:
                    r = c.get(f"/jobs/{job_id}")
            except httpx.HTTPError:
                continue  # 잠깐 끊긴 것은 다음 확인에서 다시 본다
            if r.status_code == 404:
                raise TrainingError("학습 서버에 작업이 없습니다 (학습 서버를 다시 띄웠을 수 있습니다)")
            state = r.json()
            if state["status"] == "failed":
                raise TrainingError(f"GPU PC 학습 실패: {state.get('error', '')[-500:]}", retryable=state.get("retryable", True))
            if state["status"] == "canceled":
                return Outcome(False, "voice_changed", {})
            if state["status"] == "done":
                o = state["outcome"]
                adapter = None
                if o["applied"]:
                    work.mkdir(parents=True, exist_ok=True)
                    adapter = work / "adapter_best.safetensors"
                    try:
                        with _client(120) as c:
                            a = c.get(f"/jobs/{job_id}/adapter")
                        a.raise_for_status()
                    except httpx.HTTPError as e:
                        raise TrainingError(f"학습한 어댑터를 받지 못했습니다: {type(e).__name__}") from e
                    adapter.write_bytes(a.content)
                return Outcome(o["applied"], o["reason"], o["report"], adapter=adapter, gpu_seconds=o["gpu_seconds"])
    finally:
        _cancel(job_id)  # 끝났으면 받은 녹음·중간 파일을 지우고, 도중에 멈췄으면 학습을 취소한다
