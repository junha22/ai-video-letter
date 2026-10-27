"""RunPod 서버리스 엔드포인트 호출. /run으로 넣고 /status를 폴링한다."""

import time

import httpx

from ..config import settings

_BASE = "https://api.runpod.ai/v2"


class RunPodError(RuntimeError):
    pass


def run(endpoint_id: str, payload: dict, timeout: float = 900) -> tuple[dict, float]:
    """(output, gpu_seconds)를 돌려준다. gpu_seconds는 RunPod가 보고한 executionTime 기준.

    endpoint_id 자리에 http(s) 주소를 넣으면 RunPod 대신 로컬 테스트 서버를 부른다
    (핸들러를 `python gpu_worker/xxx_handler.py --rp_serve_api`로 띄운 경우).
    """
    if endpoint_id.startswith(("http://", "https://")):
        return _run_local(endpoint_id.rstrip("/"), payload, timeout)
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


def _run_local(base_url: str, payload: dict, timeout: float) -> tuple[dict, float]:
    """RunPod SDK의 로컬 테스트 서버. /runsync 한 번으로 끝까지 기다리고, 걸린 시간을 GPU 시간으로 기록한다.
    GPU PC를 터널로 열어 둔 경우(gpu_worker/gateway.py) RUNPOD_API_KEY를 그 게이트웨이 토큰으로 보낸다."""
    started = time.monotonic()
    headers = {"Authorization": f"Bearer {settings.runpod_api_key}"} if settings.runpod_api_key else {}
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(f"{base_url}/runsync", headers=headers, json={"input": payload})
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as e:
        raise RunPodError(f"로컬 핸들러({base_url})에 연결하지 못했습니다: {e}") from e
    if data.get("status") != "COMPLETED":
        raise RunPodError(f"로컬 핸들러 작업 {data.get('status')}: {str(data.get('error'))[:300]}")
    return data.get("output") or {}, round(time.monotonic() - started, 2)


def cost(gpu_seconds: float) -> float:
    return round(gpu_seconds * settings.runpod_cost_per_second, 6)
