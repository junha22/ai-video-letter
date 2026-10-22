"""사진 + 음성 -> 모바일용 MP4.

runpod = FLOAT + 입 모양 LoRA를 RunPod에서 실행 (backend/gpu_worker/video_handler.py),
local = 사진에 천천히 확대되는 효과만 준 개발용 대체.
어느 쪽이든 마지막 인코딩 단계에서 'AI로 만든 영상' 표시를 영상에 직접 입힌다.
"""

import base64
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from ..config import settings
from . import audio, runpod

WIDTH, HEIGHT = 720, 900  # 4:5 세로 화면
FPS = 25
TAIL_SECONDS = 0.6
LABEL = "AI로 만든 영상"

_FONT_CANDIDATES = [
    "C:/Windows/Fonts/malgunbd.ttf",
    "C:/Windows/Fonts/malgun.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",
]


@dataclass
class VideoResult:
    provider: str
    duration: float
    gpu_seconds: float = 0.0
    cost_usd: float = 0.0


def _font(size: int) -> tuple[ImageFont.ImageFont, bool]:
    for path in _FONT_CANDIDATES:
        if Path(path).exists():
            return ImageFont.truetype(path, size), True
    return ImageFont.load_default(size=size), False


def _crop_portrait(photo: Image.Image, face: list[int]) -> Image.Image:
    """얼굴이 화면 가로의 약 38%, 세로 42% 지점에 오도록 4:5로 자른다."""
    x, y, w, h = face
    cx, cy = x + w / 2, y + h / 2
    crop_w = min(w / 0.38, photo.width, photo.height * WIDTH / HEIGHT)
    crop_h = crop_w * HEIGHT / WIDTH
    left = min(max(cx - crop_w / 2, 0), photo.width - crop_w)
    top = min(max(cy - crop_h * 0.42, 0), photo.height - crop_h)
    return photo.crop((round(left), round(top), round(left + crop_w), round(top + crop_h)))


def _badge() -> Image.Image:
    layer = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    font, has_korean = _font(26)
    text = LABEL if has_korean else "AI GENERATED"
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    pad_x, pad_y = 18, 10
    box = (24, 24, 24 + right - left + pad_x * 2, 24 + bottom - top + pad_y * 2)
    draw.rounded_rectangle(box, radius=22, fill=(0, 0, 0, 150))
    draw.text((box[0] + pad_x - left, box[1] + pad_y - top), text, font=font, fill=(255, 255, 255, 255))
    return layer


def _encode(inputs: list[str], video_filter: str, audio_input: int, duration: float, out_mp4: Path) -> None:
    audio.run_ffmpeg(
        [
            "-y",
            *inputs,
            "-filter_complex",
            f"{video_filter};[{audio_input}:a]apad=pad_dur={TAIL_SECONDS}[a]",
            "-map", "[v]", "-map", "[a]",
            "-t", f"{duration:.2f}",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-profile:v", "main", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k", "-ar", "48000",
            "-movflags", "+faststart",
            str(out_mp4),
        ]
    )


def render(photo_path: Path, face: list[int], audio_wav: Path, out_mp4: Path, poster_jpg: Path) -> VideoResult:
    duration = audio.wav_duration(audio_wav) + TAIL_SECONDS
    portrait = _crop_portrait(Image.open(photo_path).convert("RGB"), face)
    badge = _badge()

    poster = portrait.resize((WIDTH, HEIGHT), Image.LANCZOS).convert("RGBA")
    poster.alpha_composite(badge)
    poster.convert("RGB").save(poster_jpg, quality=88)

    with tempfile.TemporaryDirectory() as tmp:
        badge_png = Path(tmp) / "badge.png"
        badge.save(badge_png)

        if settings.video_provider == "runpod":
            return _render_runpod(photo_path, face, audio_wav, badge_png, duration, out_mp4, poster_jpg, Path(tmp))

        # 확대 효과가 부드럽도록 2배 크기로 넣는다
        frame_png = Path(tmp) / "frame.png"
        portrait.resize((WIDTH * 2, HEIGHT * 2), Image.LANCZOS).save(frame_png)
        zoom = (
            f"[0:v]zoompan=z='min(1+0.0005*on,1.08)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
            f":d=1:s={WIDTH}x{HEIGHT}:fps={FPS}[bg];[bg][1:v]overlay=0:0,format=yuv420p[v]"
        )
        _encode(
            ["-loop", "1", "-framerate", str(FPS), "-i", str(frame_png), "-i", str(badge_png), "-i", str(audio_wav)],
            zoom,
            2,
            duration,
            out_mp4,
        )
    return VideoResult("local", round(duration, 2))


def _model_options() -> dict:
    """.env의 VIDEO_* 값 중 채워진 것만 핸들러에 넘긴다 (비어 있으면 핸들러 기본값)."""
    options = {
        "lora_strength": settings.video_lora_strength,
        "emo": settings.video_emotion or None,
        "a_cfg_scale": settings.video_a_cfg_scale,
        "e_cfg_scale": settings.video_e_cfg_scale,
        "seed": settings.video_seed,
    }
    return {k: v for k, v in options.items() if v is not None}


def _render_runpod(
    photo_path: Path,
    face: list[int],
    audio_wav: Path,
    badge_png: Path,
    duration: float,
    out_mp4: Path,
    poster_jpg: Path,
    tmp: Path,
) -> VideoResult:
    # 입력·출력 계약은 backend/gpu_worker/video_handler.py 참고.
    # FLOAT은 학습 때와 같은 방식으로 얼굴을 직접 잘라야 품질이 나와서, 4:5로 자른 사진 대신
    # 저장된 원본 사진(최대 1280px)과 얼굴 위치를 보낸다. 얼굴 검출이 실패하면 핸들러가 이 위치로 자른다.
    output, gpu_seconds = runpod.run(
        settings.runpod_video_endpoint_id,
        {
            "image_b64": base64.b64encode(photo_path.read_bytes()).decode(),
            "face": face,
            "audio_b64": base64.b64encode(audio_wav.read_bytes()).decode(),
            "fps": FPS,
            **_model_options(),
        },
    )
    if "video_b64" not in output:
        raise runpod.RunPodError(f"영상 응답에 video_b64가 없습니다: {list(output)}")
    model_mp4 = tmp / "model.mp4"
    model_mp4.write_bytes(base64.b64decode(output["video_b64"]))

    # FLOAT 영상(정사각형)을 4:5 화면 가운데에 두고, 남는 위아래는 같은 영상을 흐리게 확대해서 채운다.
    # 음성 뒤 여백(TAIL_SECONDS) 동안은 마지막 프레임을 유지한다.
    fit = (
        f"[0:v]fps={FPS},tpad=stop_mode=clone:stop_duration={TAIL_SECONDS},split=2[m1][m2];"
        f"[m1]scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,crop={WIDTH}:{HEIGHT},boxblur=20:2[bg];"
        f"[m2]scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease[fg];"
        f"[bg][fg]overlay=(W-w)/2:(H-h)/2[base];[base][1:v]overlay=0:0,format=yuv420p[v]"
    )
    # 모델 영상의 소리 대신 원본 TTS 음성을 쓴다
    _encode(["-i", str(model_mp4), "-i", str(badge_png), "-i", str(audio_wav)], fit, 2, duration, out_mp4)

    # 사진 구도와 영상 구도가 달라서 포스터를 실제 영상 첫 화면으로 바꾼다
    audio.run_ffmpeg(["-y", "-i", str(out_mp4), "-frames:v", "1", "-q:v", "3", str(poster_jpg)])
    return VideoResult("runpod", round(duration, 2), gpu_seconds, runpod.cost(gpu_seconds))
