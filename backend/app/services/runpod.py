"""RunPod 서버리스 엔드포인트 호출. /run으로 넣고 /status를 폴링한다."""

import time

import httpx

from ..config import settings

_BASE = "https://api.runpod.ai/v2"


class RunPodError(RuntimeError):
    pass


def run(endpoint_id: str, payload: dict, timeout: float = 900) -> tuple[dict, float]:
    """(output, gpu_seconds)를 돌려준다. gpu_seconds는 RunPod가 보고한 executionTime 기준."""
    if not settings.runpod_api_key or not endpoint_id:
        raise RunPodError("RUNPOD_API_KEY 또는 엔드포인트 ID가 설정되지 않았습니다.")
    headers = {"Authorization": f"Bearer {settings.runpod_api_key}"}
    with httpx.Client(timeout=60) as client:
        resp = client.post(f"{_BASE}/{endpoint_id}/run", headers=headers, json={"input": payload})
        resp.raise_for_status()
        job_id = resp.json()["id"]
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            time.sleep(2)
            status = client.get(f"{_BASE}/{endpoint_id}/status/{job_id}", headers=headers).json()
            state = status.get("status")
            if state == "COMPLETED":
                return status.get("output") or {}, (status.get("executionTime") or 0) / 1000
            if state in ("FAILED", "CANCELLED", "TIMED_OUT"):
                raise RunPodError(f"RunPod 작업 {state}: {str(status.get('error'))[:300]}")
        client.post(f"{_BASE}/{endpoint_id}/cancel/{job_id}", headers=headers)
        raise RunPodError("RunPod 작업 시간 초과")


def cost(gpu_seconds: float) -> float:
    return round(gpu_seconds * settings.runpod_cost_per_second, 6)
