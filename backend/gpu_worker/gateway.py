"""GPU PC 게이트웨이: 이 PC의 TTS 서버와 영상 서버를 주소 하나로 묶고 토큰으로 막는다.

Azure의 워커가 Tailscale Funnel(https://<PC 이름>.<tailnet>.ts.net)을 거쳐 이 PC의 GPU 서버를 부를 때 쓴다.
  /tts/...    → TTS 서버   (기본 http://127.0.0.1:8100)
  /video/...  → 영상 서버  (기본 http://127.0.0.1:8010, RunPod 로컬 테스트 서버라 자체 인증이 없다)
  /health     → 토큰 없이 두 서버 상태만 알려 준다 (/tts/health도 TTS 서버처럼 토큰 없이 연다)

토큰은 X-API-Key 또는 Authorization: Bearer로 받는다. 백엔드(Azure) 설정:
  WEMEET_TTS_URL=https://<funnel>/tts        WEMEET_TTS_API_KEY=<토큰>
  RUNPOD_VIDEO_ENDPOINT_ID=https://<funnel>/video   RUNPOD_API_KEY=<토큰>

실행: npm run gpu (TTS·영상 서버와 같이 띄운다). 직접 띄울 때:
  GPU_GATEWAY_TOKEN=<토큰> python gpu_worker/gateway.py --port 8200
요청·응답 본문(음성·사진·영상)은 로그에 남기지 않는다.
"""

import argparse
import hmac
import logging
import os
import time
from contextlib import asynccontextmanager

import httpx
import uvicorn
from fastapi import FastAPI, Request, Response

log = logging.getLogger("gpu_gateway")

TOKEN = os.environ.get("GPU_GATEWAY_TOKEN", "")
UPSTREAMS = {
    "tts": os.environ.get("GATEWAY_TTS_URL", "http://127.0.0.1:8100").rstrip("/"),
    "video": os.environ.get("GATEWAY_VIDEO_URL", "http://127.0.0.1:8010").rstrip("/"),
}
HEALTH_PATHS = {"tts": "/health", "video": "/openapi.json"}  # 영상 서버(RunPod)에는 상태 확인 경로가 없다
# 영상 생성(/runsync)은 긴 대본이면 1분 가까이, GPU를 다른 작업과 나눠 쓰면 몇 분 걸린다
TIMEOUT = httpx.Timeout(connect=5, read=900, write=60, pool=5)
HOP_BY_HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailers",
              "transfer-encoding", "upgrade", "host", "content-length", "content-encoding"}

client: httpx.AsyncClient | None = None


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global client
    client = httpx.AsyncClient(timeout=TIMEOUT)
    yield
    await client.aclose()


app = FastAPI(title="GPU gateway", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)


def _authorized(request: Request) -> bool:
    given = request.headers.get("x-api-key") or ""
    auth = request.headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        given = given or auth[7:]
    return bool(TOKEN) and hmac.compare_digest(given.encode(), TOKEN.encode())


@app.get("/health")
async def health():
    status = {}
    for name, base in UPSTREAMS.items():
        try:
            r = await client.get(base + HEALTH_PATHS[name], timeout=3)
            status[name] = "ok" if r.status_code == 200 else f"http {r.status_code}"
        except httpx.HTTPError:
            status[name] = "unreachable"
    return status


@app.api_route("/{service}/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def forward(service: str, path: str, request: Request):
    if service not in UPSTREAMS:
        return Response(status_code=404)
    # TTS 서버의 /health는 원래 키 없이 열려 있고, 백엔드(wemeet_tts.health)도 키 없이 묻는다
    public = request.method == "GET" and service == "tts" and path == "health"
    if not public and not _authorized(request):
        return Response(status_code=401)
    started = time.monotonic()
    headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP_BY_HOP | {"authorization"}}
    try:
        upstream = await client.request(
            request.method, f"{UPSTREAMS[service]}/{path}", params=request.query_params,
            headers=headers, content=await request.body(),
        )
    except httpx.HTTPError as e:
        log.warning("%s %s/%s → 연결 실패 (%s)", request.method, service, path, type(e).__name__)
        return Response(status_code=502)
    log.info("%s %s/%s → %s (%.1f초)", request.method, service, path, upstream.status_code, time.monotonic() - started)
    out_headers = {k: v for k, v in upstream.headers.items() if k.lower() not in HOP_BY_HOP}
    return Response(content=upstream.content, status_code=upstream.status_code, headers=out_headers)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")  # Funnel이 이 PC 안에서 접속하므로 밖으로 열지 않는다
    parser.add_argument("--port", type=int, default=8200)
    args = parser.parse_args()
    if len(TOKEN) < 24:
        raise SystemExit("[gateway] GPU_GATEWAY_TOKEN을 24자 이상 임의 문자열로 정해 주세요 (backend/.env).")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    uvicorn.run(app, host=args.host, port=args.port, access_log=False)


if __name__ == "__main__":
    main()
