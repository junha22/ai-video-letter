"""사진 + 음성 -> 모바일용 MP4.

runpod = 선정한 립싱크 모델(학습 불필요형)을 RunPod에서 실행, local = 사진에 천천히 확대되는 효과만 준 개발용 대체.
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
            return _render_runpod(portrait, audio_wav, badge_png, duration, out_mp4, Path(tmp))

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


def _render_runpod(
    portrait: Image.Image, audio_wav: Path, badge_png: Path, duration: float, out_mp4: Path, tmp: Path
) -> VideoResult:
    image_jpg = tmp / "portrait.jpg"
    portrait.resize((WIDTH, HEIGHT), Image.LANCZOS).save(image_jpg, quality=92)
    output, gpu_seconds = runpod.run(
        settings.runpod_video_endpoint_id,
        {
            "image_b64": base64.b64encode(image_jpg.read_bytes()).decode(),
            "audio_b64": base64.b64encode(audio_wav.read_bytes()).decode(),
            "fps": FPS,
        },
    )
    if "video_b64" not in output:
        raise runpod.RunPodError(f"영상 응답에 video_b64가 없습니다: {list(output)}")
    model_mp4 = tmp / "model.mp4"
    model_mp4.write_bytes(base64.b64decode(output["video_b64"]))
    fit = (
        f"[0:v]scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease,"
        f"pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2,fps={FPS}[base];[base][1:v]overlay=0:0,format=yuv420p[v]"
    )
    # 모델 영상의 소리 대신 원본 TTS 음성을 쓴다
    _encode(["-i", str(model_mp4), "-i", str(badge_png), "-i", str(audio_wav)], fit, 2, duration, out_mp4)
    return VideoResult("runpod", round(duration, 2), gpu_seconds, runpod.cost(gpu_seconds))
