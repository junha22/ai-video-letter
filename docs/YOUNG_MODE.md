# 어린 시절 모드 (테스트 기능)

영상 편지를 **자녀의 어린 시절 모습과 목소리**로 만든다. 영상 만들기 화면에서 "어린 시절 모습으로 만들기 (테스트)"를 체크하면 된다.

```
대본 → TTS(내 목소리) → [목소리 어리게] → [사진 어리게, 사용자당 처음 한 번] → FLOAT → 영상
```

| 바꾸는 것 | 방법 | 어디서 |
|---|---|---|
| 목소리 | 음높이와 목소리 울림(포먼트)을 `YOUNG_VOICE_PITCH`배로 올린다. 길이는 그대로라 립싱크가 어긋나지 않는다 | 백엔드 (ffmpeg, `audio.make_younger`) |
| 사진 | Qwen-Image-2.1 Turbo(8비트)로 편집. 결과는 `photo/young.png`에 두고 다음 영상부터 그대로 쓴다 | GPU PC의 ComfyUI (`services/young.py`) |

## 테스트 1: GPU 없이 (목소리만)

`COMFYUI_URL`을 비워 두면 사진은 원본을 그대로 쓰고 목소리만 바꾼다.

1. `npm run dev:all`
2. 메시지 화면에서 **어린 시절 모습으로 만들기**를 체크하고 영상 만들기
3. 목소리 높이를 바꿔 보려면 `backend/.env`의 `YOUNG_VOICE_PITCH`를 고치고 워커를 다시 켠 뒤 "다시 만들기"
   - 기본 1.25. 남자 목소리는 1.3~1.4, 여자 목소리는 1.15~1.2도 들어 볼 것
   - 너무 올리면 헬륨 목소리처럼 들린다

## 테스트 2: GPU PC에서 사진까지

### ComfyUI 준비 (한 번)

1. ComfyUI 설치 (최신 버전이어야 Qwen-Image-2.1 블록이 있다)
   - Windows: [ComfyUI 포터블](https://github.com/comfyanonymous/ComfyUI/releases)을 받거나
   - `git clone https://github.com/comfyanonymous/ComfyUI.git` 후 CUDA용 torch가 있는 가상환경에서 `pip install -r requirements.txt`
2. 모델 파일 3개를 [Comfy-Org/Qwen-Image-2.1](https://huggingface.co/Comfy-Org/Qwen-Image-2.1)에서 받아 넣는다

   | 파일 | 넣을 곳 | 크기 |
   |---|---|---|
   | `diffusion_models/qwen_image_2.1_turbo_int8_convrot.safetensors` | `ComfyUI/models/diffusion_models/` | 6.76GB |
   | `text_encoders/qwen3vl_8b_int8_convrot.safetensors` | `ComfyUI/models/text_encoders/` | 8.71GB |
   | `vae/qwen_image_2.1_vae_bf16.safetensors` | `ComfyUI/models/vae/` | 0.64GB |

3. 실행 (이 PC 안에서만 열기)
   ```
   python main.py --listen 127.0.0.1 --port 8188 --reserve-vram 4
   ```
   - `--reserve-vram 4`: TTS 서버(약 3.2GB)가 쓸 자리를 남긴다. 메모리 부족 오류가 나면 이 값을 조정한다
   - 사진을 다 만들면 백엔드가 `/free`를 불러 ComfyUI 모델을 내린다 (FLOAT가 쓸 자리)

### 백엔드 설정

- 같은 PC에서 백엔드를 돌릴 때: `backend/.env`에 `COMFYUI_URL=http://127.0.0.1:8188`
- Azure 백엔드에서 부를 때: GPU 게이트웨이가 `/comfy`를 ComfyUI로 넘긴다
  ```
  COMFYUI_URL=https://<PC>.<tailnet>.ts.net/comfy
  COMFYUI_API_KEY=<GPU_GATEWAY_TOKEN과 같은 값>
  ```

### 확인

1. 메시지 화면에서 체크하고 영상 만들기. **첫 영상은 사진을 만드느라 더 걸린다** (T4 기준 장당 약 33초, 모델을 처음 불러올 때는 몇 분)
2. 만든 사진: `backend/data/users/<사용자ID>/photo/young.png`
3. 사진을 다시 만들려면 사진을 새로 올리면 된다 (올릴 때 `young.png`와 기록을 지운다)

## 설정

| 변수 | 기본값 | 설명 |
|---|---|---|
| `COMFYUI_URL` | (없음) | 비우면 원본 사진을 쓰고 목소리만 바꾼다 |
| `COMFYUI_API_KEY` | (없음) | 게이트웨이를 거칠 때 토큰 (`X-API-Key`) |
| `YOUNG_AGE` | 6 | 지시문의 나이. 바꿔도 이미 만든 사진은 그대로다 |
| `YOUNG_VOICE_PITCH` | 1.25 | 목소리 배율. 1이면 그대로 |

## 실험으로 정한 것 (2026-11-10~11, Kaggle T4, 본인 증명사진 1장)

| 시도 | 시간 | 결과 |
|---|---|---|
| SAM (나이 변환 전용 모델, 2021) | — | 품질이 낮다 |
| Qwen Chat (웹) | — | 12~13살, 닮음 높음. 워터마크가 있고 자동으로 부를 수 없어 비교용 |
| Qwen-Image-Edit-2511, 4비트 + Lightning 4단계 | 327초 | 9~11살이지만 머리·얼굴이 평균적인 아이로 바뀐다 |
| ㄴ Lightning 없이 40단계 | 4,919초 | 4단계와 거의 같다 |
| **Qwen-Image-2.1 Turbo 8비트, 8단계** | **33초** | 아래 지시문에 따라 결과가 갈린다 |
| ㄴ + 공식 지시문 다듬기 모델 | 504초 | 닮음은 가장 높지만 거의 안 어려진다 (15~16살) |
| ㄴ 원래 모델(Turbo 아님) 25단계 / 40단계 | 292초 / 370초 | Turbo와 거의 같다 |

- **단계 수는 결과를 거의 바꾸지 않았고 지시문이 좌우했다.**
- "같은 얼굴형 유지"를 넣으면 거의 안 어려진다. 아이는 얼굴 비율 자체가 달라서다.
- 나이 숫자(7·5·4살)만 바꾸면 13~14살에서 멈췄다. **"같은 옷·같은 구도 유지"** 가 정장과 어른 어깨를 붙잡아 두었기 때문이다.
- 옷을 아이 옷으로 풀고 **"조금 멀리서 찍은 구도(머리를 작게)"** 를 넣자 9~11살로 가장 어려 보였다 (실험의 A2).
- 같은 편집을 두 번 돌리면 피부·머리에 잡티가 쌓여서 더 나빠졌다.
- 지금 지시문(`services/young.py`의 `PROMPT`)은 A2에서 두 군데를 바꿨다: 옷을 특정하지 않고 "원본과 비슷한 아이 옷"으로, 안경은 "쓴 사람만". **이 두 군데는 아직 실제로 돌려 보지 않았다.**

## 알아 둘 점

- **라이선스**: Qwen-Image-2.1은 Qwen Research License라서 **상업적으로 쓰려면 별도 계약**이 필요하다. 출시할 때는 Qwen-Image-Edit-2511(Apache 2.0)이나 유료 API를 다시 검토한다.
- **본인 확인이 없다**: 남의 사진으로 아이 영상을 만들 수 있다. 정식 기능으로 열기 전에 본인 확인과 동의 항목(사진 변환)을 추가해야 한다.
- **ComfyUI에 남는 파일**: 원본 사진이 ComfyUI `input` 폴더에 `ongi_user_<ID>.jpg`로 남는다 (사용자별로 덮어쓴다). 결과는 임시 폴더라 ComfyUI를 다시 켜면 지워진다. 테스트가 끝나면 `input` 폴더를 비운다.
- **목소리 변환은 단순한 음높이 변환**이라 조금 기계적으로 들릴 수 있다.
- 만든 사진에서 얼굴을 못 찾으면 영상 만들기가 실패로 끝난다. 사진의 흐림·얼굴 크기 검사는 만든 사진에는 적용하지 않는다 (매끈하고 멀리서 찍은 구도라 걸리기 쉽다).
