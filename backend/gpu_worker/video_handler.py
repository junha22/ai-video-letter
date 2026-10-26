"""RunPod 서버리스 영상 핸들러 (FLOAT + 입 모양 LoRA).

사진 1장 + 음성 -> 입이 움직이는 512x512 영상(소리 없음).
백엔드(app/services/video.py)가 이 영상을 받아 4:5 화면 맞춤, 원래 음성 입히기, 'AI로 만든 영상' 표시를 한다.

입력:
  image_b64      str            사진 (jpg/png)
  audio_b64      str            음성 (wav). 내부에서 16kHz로 바꿔 읽는다
  face           [x, y, w, h]   선택. 사진 속 얼굴 위치. FLOAT 얼굴 검출이 실패하면 이 위치로 자른다
  fps            int            선택. 25만 지원 (FLOAT 학습 기준)
  seed           int            선택. 주면 같은 입력에 항상 같은 영상, 없으면 매번 조금씩 다름
  lora_strength  float          선택. 0 = 원본 FLOAT, 1 = 입 모양 파인튜닝 (기본 1)
  emo            str            선택. angry|disgust|fear|happy|neutral|sad|surprise. 비우면 음성에서 추정
  a_cfg_scale    float          선택. 음성 반영 강도 (기본 2)
  e_cfg_scale    float          선택. 감정 반영 강도 (기본 1)
  nfe            int            선택. ODE 단계 수 (기본 10)
  -- 생성 조정 (float_tuning.py, Kaggle 노트북 float_infer.ipynb에서 옮김). 주지 않으면 FLOAT 원래 동작 --
  r_cfg_scale    float          선택. 사진 충실도. 올리면 시선·기본 표정이 사진에서 덜 벗어난다 (기본 1 = 끔, 노트북 추천 3)
  ref_mode       str            선택. 사진 충실도 적용 범위 free|eye|all (기본 free = 입·감정은 살림)
  eye_stable     float          선택. 0~1. 시선 떨림을 줄이고 사진 속 시선 쪽으로 당김 (기본 0 = 끔, 노트북 추천 0.4)
  blink_gap      float          선택. 초. 이보다 가깝게 붙은 깜빡임을 지움 (기본 0 = 끔, 노트북 추천 3)
  dejump         bool           선택. 고개·표정이 갑자기 튀는 프레임의 앞뒤만 부드럽게 (기본 false, 노트북 추천 true)
출력:
  {"video_b64": str(mp4), "width", "height", "frames", "fps", "crop", "notes", "seconds"}
  crop: 얼굴을 어떻게 잘랐는지 (float = FLOAT 검출기, face_box = 입력 face, center = 가운데)
  notes: 생성 조정 기록 (예: "깜빡임 6회 중 3회 남김")

준비 (GPU 서버/이미지에서 한 번, Linux + CUDA):
  git clone https://github.com/deepbrainai-research/float.git gpu_worker/float
  git -C gpu_worker/float checkout 3b5b2dfc3e65df26e7fbba17d9adb3f43747851c
  pip install torch==2.0.1 torchvision==0.15.2 torchaudio==2.0.2 --index-url https://download.pytorch.org/whl/cu118
  pip install -r gpu_worker/float/requirements.txt runpod
  체크포인트 -> gpu_worker/float/checkpoints/
    float.pth                                   (cd gpu_worker/float && sh download_checkpoints.sh)
    wav2vec2-base-960h/                         (huggingface.co/facebook/wav2vec2-base-960h)
    wav2vec-english-speech-emotion-recognition/ (huggingface.co/r-f/wav2vec-english-speech-emotion-recognition)
  LoRA: gpu_worker/weights/float_lora_best.pt (이 저장소에 포함)
  얼굴 검출 가중치(face_alignment)는 처음 실행할 때 자동으로 받는다. 이미지로 만들 때는 빌드 중에 한 번 실행해 둔다.
  경로는 환경변수 FLOAT_ROOT, FLOAT_CKPT_DIR, FLOAT_LORA_PATH로 바꿀 수 있다.

Windows(Python 3.10)에서도 돈다. 이 PC에서 TTS 서버와 같이 띄우는 방법은 README '이 PC(Windows)에서 …' 참고.

로컬 테스트 (GPU가 있는 Linux/WSL PC, RunPod 배포 없이 웹과 연결):
  python gpu_worker/video_handler.py --rp_serve_api --rp_api_host 0.0.0.0 --rp_api_port 8010
  백엔드 .env: VIDEO_PROVIDER=runpod, RUNPOD_VIDEO_ENDPOINT_ID=http://<그 PC 주소>:8010

라이선스: FLOAT는 비상업 라이선스(CC BY-NC)다. 비상업 연구·PoC 용도로만 쓴다.
"""

from __future__ import annotations  # FLOAT 권장 환경(Python 3.8)에서도 tuple[...] 표기가 동작하도록

import argparse
import base64
import os
import sys
import tempfile
import time
from fractions import Fraction
from pathlib import Path

HERE = Path(__file__).resolve().parent
FLOAT_ROOT = Path(os.getenv("FLOAT_ROOT") or HERE / "float").resolve()
CKPT_DIR = Path(os.getenv("FLOAT_CKPT_DIR") or FLOAT_ROOT / "checkpoints")
LORA_PATH = Path(os.getenv("FLOAT_LORA_PATH") or HERE / "weights" / "float_lora_best.pt")
# FLOAT의 styledecoder.py가 .cuda()를 직접 부르기 때문에 실제로는 GPU가 필요하다. 0 = 첫 번째 GPU
_device = os.getenv("FLOAT_DEVICE", "0")
DEVICE = int(_device) if _device.isdigit() else _device

if not (FLOAT_ROOT / "generate.py").is_file():
    sys.exit(f"[video_handler] FLOAT 소스가 없습니다: {FLOAT_ROOT} (위 '준비' 참고, 또는 FLOAT_ROOT 지정)")
for need in [CKPT_DIR / "float.pth", CKPT_DIR / "wav2vec2-base-960h",
             CKPT_DIR / "wav2vec-english-speech-emotion-recognition", LORA_PATH]:
    if not need.exists():
        sys.exit(f"[video_handler] 파일이 없습니다: {need} (위 '준비' 참고)")

sys.path.insert(0, str(FLOAT_ROOT))
# RunPod SDK는 기본값(DEBUG)이면 결과 전체(영상 base64, 1건에 수백 KB)를 로그에 남긴다.
# 얼굴·목소리가 담긴 영상이 로그에 쌓이지 않게 INFO(작업 시작·끝만)로 둔다. 디버깅할 때만 RUNPOD_LOG_LEVEL=DEBUG
os.environ.setdefault("RUNPOD_LOG_LEVEL", "INFO")

import av  # noqa: E402
import cv2  # noqa: E402
import numpy as np  # noqa: E402
import runpod  # noqa: E402
import torch  # noqa: E402
from generate import InferenceAgent, InferenceOptions  # noqa: E402  (FLOAT 원본 generate.py)

import float_tuning as tuning  # noqa: E402  (같은 폴더)

EMOTIONS = ("angry", "disgust", "fear", "happy", "neutral", "sad", "surprise")


class LoRA:
    """FLOAT FMT의 Linear 32개에 LoRA를 forward hook으로 붙인다.

    W x + b + strength * scale * B (A x). strength는 요청마다 바꿀 수 있어서
    같은 엔드포인트로 원본(0)과 파인튜닝(1)을 비교할 수 있다.
    """

    def __init__(self, fmt: torch.nn.Module, path: Path):
        state = torch.load(path, map_location="cpu", weights_only=True)
        modules = dict(fmt.named_modules())
        self.strength = 1.0
        self.layers = 0
        for name, entry in state.items():
            layer = modules.get(name)
            if not isinstance(layer, torch.nn.Linear):
                raise KeyError(f"LoRA 키 '{name}'에 맞는 Linear가 FLOAT FMT에 없습니다")
            A, B = entry["A"], entry["B"]
            if A.shape[1] != layer.in_features or B.shape[0] != layer.out_features:
                raise ValueError(f"LoRA 크기가 맞지 않습니다: {name} A={tuple(A.shape)} B={tuple(B.shape)}")
            w = layer.weight
            layer.register_forward_hook(
                self._hook(A.to(w.device, w.dtype), B.to(w.device, w.dtype), float(entry.get("scale", 1.0)))
            )
            self.layers += 1

    def _hook(self, A: torch.Tensor, B: torch.Tensor, scale: float):
        def hook(module, inputs, output):
            if self.strength == 0.0:
                return output
            return output + (inputs[0] @ A.t() @ B.t()) * (scale * self.strength)

        return hook


def _options() -> argparse.Namespace:
    opt = InferenceOptions().initialize(argparse.ArgumentParser()).parse_args([])
    opt.ckpt_path = str(CKPT_DIR / "float.pth")
    opt.wav2vec_model_path = str(CKPT_DIR / "wav2vec2-base-960h")
    opt.audio2emotion_path = str(CKPT_DIR / "wav2vec-english-speech-emotion-recognition")
    opt.rank, opt.ngpus = DEVICE, 1
    return opt


# 콜드 스타트 때 한 번만 불러온다
_started = time.monotonic()
OPT = _options()
AGENT = InferenceAgent(OPT)
ADAPTER = LoRA(AGENT.G.fmt, LORA_PATH)
REF_GUIDANCE = tuning.RefGuidance(AGENT.G.fmt)
print(f"[video_handler] FLOAT + LoRA({LORA_PATH.name}, {ADAPTER.layers}층) 준비 {time.monotonic() - _started:.1f}초", flush=True)


def _crop_box(img: np.ndarray, face: list, size: int) -> np.ndarray:
    """FLOAT generate.py의 process_img와 같은 규칙(얼굴 박스 긴 변의 1.6배 정사각형, 모자라면 검은 여백)."""
    x, y, w, h = (int(v) for v in face)
    bs = max(int(max(w, h) / 2 * 1.6), 1)
    my, mx = int(y + h / 2) + bs, int(x + w / 2) + bs
    padded = cv2.copyMakeBorder(img, bs, bs, bs, bs, cv2.BORDER_CONSTANT, value=0)
    crop = padded[my - bs : my + bs, mx - bs : mx + bs]
    return cv2.resize(crop, (size, size), interpolation=cv2.INTER_AREA if crop.shape[0] > size else cv2.INTER_CUBIC)


def _crop(img: np.ndarray, face) -> tuple[np.ndarray, str]:
    size = AGENT.data_processor.input_size
    try:
        # 학습 때와 같은 FLOAT 자체 얼굴 검출·자르기를 먼저 쓴다
        return AGENT.data_processor.process_img(img), "float"
    except Exception as e:  # 얼굴을 못 찾으면 bboxes[0]에서 IndexError
        print(f"[video_handler] FLOAT 얼굴 검출 실패 ({type(e).__name__}), 대체 자르기 사용", flush=True)
    if face and len(face) == 4:
        return _crop_box(img, face, size), "face_box"
    h, w = img.shape[:2]
    box = min(h, w) / 1.6  # 자른 정사각형이 사진 짧은 변과 같아지는 크기
    return _crop_box(img, [(w - box) / 2, (h - box) / 2, box, box], size), "center"


@torch.no_grad()
def _generate(crop: np.ndarray, audio_path: str, *, seed, emo, a_cfg_scale, e_cfg_scale, nfe,
              r_cfg_scale, ref_mode, eye_stable, blink_gap, dejump) -> tuple[torch.Tensor, list[str]]:
    G, dp = AGENT.G, AGENT.data_processor
    s = dp.transform(image=crop)["image"].unsqueeze(0)
    a = dp.default_aud_loader(audio_path).unsqueeze(0)
    # FLOAT.sample은 인자 대신 opt.nfe / opt.fix_noise_seed / opt.seed를 읽는다
    OPT.nfe = nfe
    OPT.fix_noise_seed = seed is not None
    if seed is not None:
        OPT.seed = seed

    # FLOAT.inference와 같은 순서(사진 인코딩 → 움직임 생성 → 프레임 복원)를 직접 밟는다.
    # 중간에 나오는 움직임을 눈 후처리로 손질하고, 사진 인코딩 결과를 눈·입 방향 분석에 같이 쓰기 위해서다
    s_r, lam, feats = G.encode_image_into_latent(s.to(DEVICE))
    r_s = G.motion_autoencoder.dec.direction(lam)

    notes, dirs = [], None
    post = eye_stable > 0 or blink_gap > 0 or dejump
    if post or (r_cfg_scale != 1.0 and ref_mode == "eye"):
        landmarks = dp.fa.get_landmarks(crop)
        if landmarks:
            dirs = tuning.motion_directions(G, landmarks[0], s_r, lam, feats)
            notes.append(f"눈 방향 {dirs.eye_idx}, 입 방향 {dirs.mouth_idx}")
        else:
            notes.append("눈 위치를 못 찾아 눈 관련 처리를 건너뜀")
    if ref_mode == "eye" and dirs is None and r_cfg_scale != 1.0:
        ref_mode = "free"  # 눈 방향을 모르면 'all'처럼 표정까지 당기지 않도록 추천 범위로 대신한다
        notes.append("사진 충실도 범위를 free로 대신함")
    REF_GUIDANCE.scale, REF_GUIDANCE.mode = r_cfg_scale, ref_mode
    REF_GUIDANCE.eye_q = dirs.eye if dirs is not None else None

    sample = G.sample({"r_s": r_s, "a": a}, a_cfg_scale=a_cfg_scale, r_cfg_scale=1.0, e_cfg_scale=e_cfg_scale,
                      emo=emo, nfe=nfe, seed=seed)
    if post and dirs is not None:
        sample, post_notes = tuning.eye_postprocess(sample, r_s, dirs, OPT.fps,
                                                    stable=eye_stable, blink_gap=blink_gap, dejump=dejump)
        notes += post_notes
    d_hat = G.decode_latent_into_image(s_r=s_r, s_r_feats=feats, r_d=sample)["d_hat"]
    return (d_hat.unsqueeze(0) if d_hat.dim() == 3 else d_hat), notes  # (T, 3, H, W), -1~1


def _to_mp4(frames: torch.Tensor, fps: int, path: str) -> None:
    pixels = ((frames.detach().clamp(-1, 1).float().cpu() + 1) * 127.5).round().to(torch.uint8)
    pixels = pixels.permute(0, 2, 3, 1).numpy()
    with av.open(path, mode="w") as container:
        # 백엔드에서 한 번 더 인코딩하므로 여기서는 화질을 높게(crf 18) 둔다
        stream = container.add_stream("libx264", rate=Fraction(fps), options={"crf": "18", "preset": "veryfast"})
        stream.width, stream.height, stream.pix_fmt = pixels.shape[2], pixels.shape[1], "yuv420p"
        for frame in pixels:
            for packet in stream.encode(av.VideoFrame.from_ndarray(frame, format="rgb24")):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)


def handler(job):
    started = time.monotonic()
    inp = job["input"]
    if not inp.get("image_b64") or not inp.get("audio_b64"):
        raise ValueError("image_b64와 audio_b64가 필요합니다")

    fps = int(inp.get("fps") or OPT.fps)
    if fps != int(OPT.fps):
        raise ValueError(f"FLOAT은 {OPT.fps:g}fps만 지원합니다 (요청 {fps})")
    emo = (inp.get("emo") or "").strip().lower() or None
    if emo and emo not in EMOTIONS:
        raise ValueError(f"emo는 {', '.join(EMOTIONS)} 중 하나여야 합니다 (요청 {emo})")
    seed = int(inp["seed"]) if inp.get("seed") is not None else None
    ref_mode = (inp.get("ref_mode") or "free").strip().lower()
    if ref_mode not in tuning.REF_MODES:
        raise ValueError(f"ref_mode는 {', '.join(tuning.REF_MODES)} 중 하나여야 합니다 (요청 {ref_mode})")
    eye_stable = float(inp.get("eye_stable") or 0.0)
    if not 0.0 <= eye_stable <= 1.0:
        raise ValueError(f"eye_stable은 0~1이어야 합니다 (요청 {eye_stable})")
    blink_gap = float(inp.get("blink_gap") or 0.0)
    if blink_gap < 0:
        raise ValueError(f"blink_gap은 0 이상이어야 합니다 (요청 {blink_gap})")
    dejump = str(inp.get("dejump", False)).strip().lower() in ("1", "true", "yes", "on")

    img = cv2.imdecode(np.frombuffer(base64.b64decode(inp["image_b64"]), np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("사진을 열 수 없습니다")
    crop, how = _crop(cv2.cvtColor(img, cv2.COLOR_BGR2RGB), inp.get("face"))

    ADAPTER.strength = float(inp.get("lora_strength", 1.0))
    try:
        with tempfile.TemporaryDirectory() as tmp:
            audio_path = os.path.join(tmp, "audio.wav")
            Path(audio_path).write_bytes(base64.b64decode(inp["audio_b64"]))
            frames, notes = _generate(
                crop, audio_path,
                seed=seed, emo=emo,
                a_cfg_scale=float(inp.get("a_cfg_scale", 2.0)),
                e_cfg_scale=float(inp.get("e_cfg_scale", 1.0)),
                nfe=int(inp.get("nfe", 10)),
                r_cfg_scale=float(inp.get("r_cfg_scale", 1.0)),
                ref_mode=ref_mode, eye_stable=eye_stable, blink_gap=blink_gap, dejump=dejump,
            )
            if notes:
                print(f"[video_handler] {' | '.join(notes)}", flush=True)
            mp4_path = os.path.join(tmp, "video.mp4")
            _to_mp4(frames, fps, mp4_path)
            video_b64 = base64.b64encode(Path(mp4_path).read_bytes()).decode()
        n_frames, height, width = int(frames.shape[0]), int(frames.shape[2]), int(frames.shape[3])
        del frames
    finally:
        # 한 PC에서 TTS 서버·음색 학습과 GPU를 나눠 쓸 수 있도록, 영상마다 생성에 쓴 메모리(약 4GB)를 돌려준다
        torch.cuda.empty_cache()

    return {
        "video_b64": video_b64,
        "width": width,
        "height": height,
        "frames": n_frames,
        "fps": fps,
        "crop": how,
        "lora_strength": ADAPTER.strength,
        "notes": notes,
        "seconds": round(time.monotonic() - started, 2),
    }


if __name__ == "__main__":
    runpod.serverless.start({"handler": handler})
