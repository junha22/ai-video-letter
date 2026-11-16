"""GPU PC 답장 분석 서버: 음성 답장의 받아쓰기(BuzzASR)와 운율 측정(librosa) (docs/REPLY_ANALYSIS.md).

판단 규칙(후처리·평소 목소리 비교)은 백엔드(app/services/reply_analysis.py)에 있고, LLM 판단은 백엔드가 CLOVA Studio(HCX-007)로 한다
(2026-11-16: TTS·영상 서버가 7GB를 쓰고 있어 로컬 SEED 14B는 너무 느려서 바꿈). 여기서는 음성만 다룬다.
  GET  /health    서버가 떠 있는지
  POST /stt       16kHz WAV(audio) → {text, duration, pieces, problems, seconds, ...}
  POST /prosody   WAV(audio) + 받아쓰기(text) → measure_prosody 결과

GPU는 순서대로 쓴다 (요청을 하나씩 처리한다).
  - 받아쓰기는 요청마다 자식 프로세스(reply_stt.py)가 BuzzASR(약 3.1GB)를 올렸다가 끝난다. 프로세스가 끝나야 CUDA 컨텍스트까지 돌아온다.
  - 이 서버 프로세스는 CUDA를 쓰지 않는다 → 요청이 끝나면 분석 서버가 잡은 GPU 메모리는 0이다. TTS·영상 서버는 건드리지 않는다.
음성·받아쓰기는 로그에 남기지 않고(걸린 시간·조각 수만), 받은 음성은 요청이 끝나면 지운다.

실행: npm run gpu (REPLY_ANALYSIS_PYTHON이 있을 때 같이 띄운다). 직접 (Wemeet-reply 환경의 python):
  python gpu_worker/reply_analysis_server.py --port 8400
  --gpu-report   지금 GPU 메모리 (프로세스별은 Windows에서 N/A일 수 있다)
"""

import argparse
import json
import logging
import os
import secrets
import subprocess
import sys
import threading
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND / "gpu_worker"))

try:  # 백엔드와 같은 backend/.env를 읽는다 (Wemeet-reply 환경에 python-dotenv가 있을 때)
    from dotenv import load_dotenv
    load_dotenv(BACKEND / ".env")
except ImportError:
    pass

import uvicorn  # noqa: E402
from fastapi import FastAPI, File, Form, HTTPException, UploadFile  # noqa: E402

import reply_audio  # noqa: E402

log = logging.getLogger("reply_analysis")

GPU_INDEX = os.environ.get("REPLY_GPU_INDEX", "0")
STT_MODEL = os.environ.get("REPLY_STT_MODEL", "BuzzASR/korean")
STT_TIMEOUT = 600
MAX_AUDIO_BYTES = 16 * 1024 * 1024   # 16kHz 모노 WAV 3분 = 약 5.8MB

DATA_DIR = Path(os.environ.get("DATA_DIR") or BACKEND / "data")
WORK = DATA_DIR / "reply_analysis"
STT_SCRIPT = Path(__file__).resolve().parent / "reply_stt.py"

lock = threading.Lock()  # GPU(받아쓰기)와 운율 계산을 하나씩


# ---------------------------------------------------------------- 받아쓰기 ----
def run_stt(wav: Path) -> dict:
    """자식 프로세스에서 받아쓰기. 끝나면 BuzzASR가 쓴 GPU 메모리가 모두 돌아온다"""
    out = WORK / "tmp" / f"{secrets.token_hex(8)}.json"
    started = time.monotonic()
    try:
        r = subprocess.run([sys.executable, str(STT_SCRIPT), str(wav), str(out)], capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=STT_TIMEOUT)
        if r.returncode != 0 or not out.exists():
            raise RuntimeError(f"받아쓰기 프로세스 실패 (code {r.returncode}): {r.stderr.strip()[-400:]}")
        result = json.loads(out.read_text(encoding="utf-8"))
    finally:
        out.unlink(missing_ok=True)
    result["process_seconds"] = round(time.monotonic() - started, 1)  # 프로세스 시작·모델 올리기 포함
    log.info("받아쓰기 %.1f초 (모델 올리기 %s초, 음성 %s초, 조각 %s개, 문제 %s개)", result["process_seconds"],
             result.get("load_seconds"), result.get("duration"), result.get("pieces"), len(result.get("problems", [])))
    return result


def run_prosody(wav: Path, text: str) -> dict:
    started = time.monotonic()
    result = reply_audio.measure_prosody(str(wav), text)
    result["seconds"] = round(time.monotonic() - started, 1)
    log.info("운율 %.1f초 (%s)", result["seconds"], "측정" if result.get("ok") else "말소리 부족")
    return result


def _warm_up_prosody() -> None:
    """첫 pyin 호출은 JIT 컴파일 때문에 느려서 서버가 뜰 때 한 번 돌려 둔다"""
    import numpy as np
    path = WORK / "tmp" / "warmup.wav"
    try:
        import soundfile as sf
        t = np.arange(int(4 * reply_audio.SR)) / reply_audio.SR
        sf.write(path, (0.3 * np.sin(2 * np.pi * 180 * t)).astype(np.float32), reply_audio.SR)
        with lock:
            started = time.monotonic()
            reply_audio.measure_prosody(str(path), "가나다라마바사아자차카")
        log.info("운율 준비 완료 (%.1f초)", time.monotonic() - started)
    except Exception:  # noqa: BLE001 - 준비가 안 돼도 첫 요청에서 다시 한다
        log.exception("운율 준비 실패")
    finally:
        path.unlink(missing_ok=True)


# ---------------------------------------------------------------- HTTP 서버 ----
app = FastAPI(title="Reply analysis", docs_url=None, redoc_url=None, openapi_url=None)


def _save_upload(audio: UploadFile) -> Path:
    data = audio.file.read(MAX_AUDIO_BYTES + 1)
    if len(data) > MAX_AUDIO_BYTES:
        raise HTTPException(413, "음성이 너무 커요")
    if not data:
        raise HTTPException(400, "음성이 비어 있어요")
    (WORK / "tmp").mkdir(parents=True, exist_ok=True)
    path = WORK / "tmp" / f"{secrets.token_hex(8)}.wav"
    path.write_bytes(data)
    return path


def _http_errors(fn, *args):
    try:
        return fn(*args)
    except subprocess.TimeoutExpired:
        raise HTTPException(504, "받아쓰기가 시간 안에 끝나지 않았어요")
    except Exception as e:  # noqa: BLE001 - 백엔드가 다시 시도하도록 500으로 돌려준다
        log.exception("분석 오류")
        raise HTTPException(500, f"{type(e).__name__}: {str(e)[-400:]}")


@app.get("/health")
def health():
    return {"ok": True, "stt_model": STT_MODEL, "busy": lock.locked()}


@app.post("/stt")
def stt(audio: UploadFile = File(...)):
    path = _save_upload(audio)
    try:
        with lock:
            return _http_errors(run_stt, path)
    finally:
        path.unlink(missing_ok=True)


@app.post("/prosody")
def prosody(audio: UploadFile = File(...), text: str = Form("")):
    path = _save_upload(audio)
    try:
        with lock:
            return _http_errors(run_prosody, path, text)
    finally:
        path.unlink(missing_ok=True)


# ---------------------------------------------------------------- 확인 명령 ----
def gpu_report() -> None:
    """nvidia-smi로 잰 GPU 메모리. 이 프로세스에 CUDA 컨텍스트를 만들지 않으려고 torch로 재지 않는다"""
    r = subprocess.run(["nvidia-smi", "-i", GPU_INDEX, "--query-gpu=memory.free,memory.used,memory.total",
                        "--format=csv,noheader"], capture_output=True, text=True, timeout=15)
    print("GPU 전체 (free, used, total):", r.stdout.strip() or r.stderr.strip())
    r = subprocess.run(["nvidia-smi", "-i", GPU_INDEX, "--query-compute-apps=pid,process_name,used_memory",
                        "--format=csv,noheader"], capture_output=True, text=True, timeout=15)
    print(r.stdout.strip() or "(GPU를 쓰는 프로세스 없음)")
    print("프로세스별 메모리가 [N/A]이면(Windows) 서버를 하나씩 끄면서 'GPU 전체 used'의 차이로 잰다.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")  # 게이트웨이를 거쳐서만 들어온다
    parser.add_argument("--port", type=int, default=int(os.environ.get("REPLY_ANALYSIS_PORT") or 8400))
    parser.add_argument("--gpu-report", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    (WORK / "tmp").mkdir(parents=True, exist_ok=True)
    if args.gpu_report:
        return gpu_report()
    threading.Thread(target=_warm_up_prosody, daemon=True).start()
    uvicorn.run(app, host=args.host, port=args.port, access_log=False)


if __name__ == "__main__":
    main()
