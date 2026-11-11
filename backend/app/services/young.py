"""어린 시절 모드: 사진 -> 어린 시절 모습. GPU PC의 ComfyUI에서 Qwen-Image-2.1 Turbo(8비트)로 사진을 편집한다.

실험 (docs/YOUNG_MODE.md, Kaggle T4):
- 장당 약 33초. 원래 모델 25·40단계도 결과가 거의 같아서 Turbo 8단계를 쓴다. 지시문 다듬기 모델은 8분 넘게 걸리고 덜 어려졌다
- 지시문의 나이 숫자(7·5·4살)를 바꿔도 결과는 13~14살에서 멈췄다. '같은 옷·같은 구도를 유지'하라는 문장이 정장과 어른 어깨를
  붙잡아 두었기 때문이다. 옷을 아이 옷으로 풀고 '조금 멀리서 찍은 구도'로 머리를 작게 하자 가장 어려 보였다
- 같은 편집을 두 번 돌리면 피부·머리에 잡티가 쌓여서 오히려 나빠졌다

사진은 사용자당 한 번 만들어 photo/young.png에 둔다 (worker._young_photo). 동의를 철회하면 photo 폴더째 지워진다.
모델 라이선스는 Qwen Research License라서 상업적으로 쓰려면 별도 계약이 필요하다.
"""

import time
import uuid

import httpx

from ..config import log, settings

UNET = "qwen_image_2.1_turbo_int8_convrot.safetensors"
CLIP = "qwen3vl_8b_int8_convrot.safetensors"
VAE = "qwen_image_2.1_vae_bf16.safetensors"
# 공식 Turbo 편집 템플릿(image_qwen_image_2_1_turbo_image_edit)의 8단계 시그마. 단계를 바꾸려면 이 값도 같이 바꿔야 한다
SIGMAS = "1.0, 0.978453, 0.95418, 0.926626, 0.89508, 0.845148, 0.704534, 0.414568, 0"
SEED = 42  # 같은 사진·나이면 다시 만들어도 같은 결과
RESOLUTION = 1024  # 원본을 약 1024x1024 화소로 맞춰 넣는다. 결과도 이 크기
OUTPUT_NODE = "13"
TIMEOUT = 600  # 처음 한 장은 모델(약 16GB)을 불러오느라 오래 걸린다

# 실험의 A2(가장 어려 보임)에서 두 군데를 바꿨다: 옷을 특정하지 않고 원본과 비슷한 아이 옷으로, 안경은 쓴 사람만
PROMPT = (
    "Show this exact person as a {age}-year-old child. Make it an unmistakably young child: a child-sized head, face "
    "and body, a round chubby face with baby cheeks, big eyes, a tiny nose and chin, smooth soft skin, narrow small "
    "shoulders and a short neck. Dress the child in a child's version of clothes similar to the ones in the image, with "
    "a similar style and colors. Keep the same identity so family would recognize them: the same eye shape, eyebrows, "
    "nose shape, mouth shape, skin tone, the same glasses if the person wears any, and the same hair color with a "
    "child's version of the same hairstyle. Plain white background, front-facing, photorealistic photo. Frame it "
    "slightly further away: the child's head appears smaller in the frame, with more empty white space around the "
    "head and more of the shoulders and upper body visible."
)


class YoungPhotoError(RuntimeError):
    user_message = "어린 시절 사진을 만들지 못했어요. 잠시 뒤 다시 시도해 주세요."

    def __init__(self, message: str, retryable: bool = True):
        super().__init__(message)
        self.retryable = retryable  # False면 작업 큐가 재시도하지 않는다


def workflow(image_name: str, age: int) -> dict:
    """ComfyUI API 형식. 공식 Turbo 편집 템플릿에서 지시문 다듬기만 뺀 것과 같다"""
    return {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": UNET, "weight_dtype": "default"}},
        "2": {"class_type": "QwenImage21Cache", "inputs": {"model": ["1", 0], "device": "auto", "dtype": "default"}},
        "3": {"class_type": "CLIPLoader", "inputs": {"clip_name": CLIP, "type": "qwen_image", "device": "default"}},
        "4": {"class_type": "VAELoader", "inputs": {"vae_name": VAE}},
        "5": {"class_type": "LoadImage", "inputs": {"image": image_name}},
        "6": {"class_type": "TextEncodeQwenImage21", "inputs": {
            "clip": ["3", 0], "vae": ["4", 0], "images.image_1": ["5", 0],
            "prompt": PROMPT.format(age=age), "negative_prompt": "", "resolution": RESOLUTION}},
        "7": {"class_type": "CFGGuider", "inputs": {"model": ["2", 0], "positive": ["6", 0], "negative": ["6", 1], "cfg": 1.0}},
        "8": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
        "9": {"class_type": "RandomNoise", "inputs": {"noise_seed": SEED}},
        "10": {"class_type": "ManualSigmas", "inputs": {"sigmas": SIGMAS}},
        "11": {"class_type": "SamplerCustomAdvanced", "inputs": {
            "noise": ["9", 0], "guider": ["7", 0], "sampler": ["8", 0], "sigmas": ["10", 0], "latent_image": ["6", 2]}},
        "12": {"class_type": "VAEDecode", "inputs": {"samples": ["11", 0], "vae": ["4", 0]}},
        # 결과는 ComfyUI 임시 폴더에만 둔다 (재시작하면 지워진다). 원본 사진은 input 폴더에 사용자별 같은 이름으로 덮어쓴다
        OUTPUT_NODE: {"class_type": "PreviewImage", "inputs": {"images": ["12", 0]}},
    }


def _client() -> httpx.Client:
    headers = {"X-API-Key": settings.comfyui_api_key} if settings.comfyui_api_key else {}
    return httpx.Client(base_url=settings.comfyui_url, headers=headers, timeout=httpx.Timeout(60, connect=5))


def generate(photo: bytes, name: str, age: int) -> bytes:
    """사진을 ComfyUI에 올리고 어린 시절 모습(PNG)을 받아 온다. 사진과 결과는 로그에 남기지 않는다."""
    started = time.monotonic()
    with _client() as c:
        try:
            up = c.post("/upload/image", files={"image": (name, photo, "image/jpeg")}, data={"overwrite": "true"})
            up.raise_for_status()
            resp = c.post("/prompt", json={"prompt": workflow(up.json()["name"], age), "client_id": uuid.uuid4().hex})
            if resp.status_code == 400:
                # 모델 파일이 없거나 ComfyUI가 2.1 블록을 모르는 경우. 다시 보내도 같다
                raise YoungPhotoError(f"ComfyUI가 작업을 거절했어요: {resp.text[:800]}", retryable=False)
            resp.raise_for_status()
            prompt_id = resp.json()["prompt_id"]
            while (history := c.get(f"/history/{prompt_id}").json()).get(prompt_id) is None:
                if time.monotonic() - started > TIMEOUT:
                    raise YoungPhotoError(f"어린 시절 사진이 {TIMEOUT}초 안에 끝나지 않았어요.")
                time.sleep(2)
            entry = history[prompt_id]
            if entry.get("status", {}).get("status_str") == "error":
                raise YoungPhotoError(f"ComfyUI 실행 오류: {str(entry['status'].get('messages'))[:800]}")
            image = entry["outputs"][OUTPUT_NODE]["images"][0]
            view = c.get("/view", params={"filename": image["filename"], "subfolder": image.get("subfolder", ""),
                                          "type": image.get("type", "temp")})
            view.raise_for_status()
        except httpx.HTTPError as e:
            raise YoungPhotoError(f"ComfyUI 연결 실패 ({settings.comfyui_url}): {e}") from e
        finally:
            _free(c)
    log.info("어린 시절 사진 생성 %.1f초", time.monotonic() - started)
    return view.content


def _free(c: httpx.Client) -> None:
    """GPU PC는 TTS·영상 서버와 VRAM을 나눠 쓴다. 다 만들면 ComfyUI 모델을 내려서 영상 단계가 쓸 자리를 비운다"""
    try:
        c.post("/free", json={"unload_models": True, "free_memory": True})
    except httpx.HTTPError as e:
        log.warning("ComfyUI 메모리 비우기 실패: %s", e)
