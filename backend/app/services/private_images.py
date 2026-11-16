"""Shared normalization and private metadata for user-selected album images."""
from io import BytesIO
import warnings

from fastapi import HTTPException
from PIL import Image, ImageOps, UnidentifiedImageError
from ..db import iso

MAX_UPLOAD = 15 * 1024 * 1024
MAX_PIXELS = 40_000_000
MAX_SIDE = 2048
FORMATS = {"JPEG", "PNG", "WEBP"}
MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}
PRIVATE = {"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"}


def image_info(image, endpoint: str) -> dict | None:
    if not image:
        return None
    return {"url": f"{endpoint}?v={image.version}", "width": image.width,
            "height": image.height, "updated_at": iso(image.updated_at)}


def normalize(data: bytes, max_pixels: int = MAX_PIXELS) -> tuple[bytes, int, int]:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as source:
                if source.format not in FORMATS or getattr(source, "is_animated", False):
                    raise HTTPException(415, "움직이지 않는 JPG, PNG, WebP 이미지를 선택해 주세요.")
                if source.width * source.height > max_pixels:
                    raise HTTPException(422, "이미지 해상도가 너무 커요. 4천만 화소 이하로 줄여 주세요.")
                image = ImageOps.exif_transpose(source)
                image.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)
                if image.mode in ("RGBA", "LA") or "transparency" in image.info:
                    rgba = image.convert("RGBA")
                    rgb = Image.new("RGB", image.size, (255, 250, 244))
                    rgb.paste(rgba, mask=rgba.getchannel("A"))
                    image = rgb
                else:
                    image = image.convert("RGB")
                output = BytesIO()
                # Re-encode without EXIF/location metadata or the original filename.
                image.save(output, format="JPEG", quality=90, optimize=True)
                return output.getvalue(), image.width, image.height
    except HTTPException:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombWarning, Image.DecompressionBombError):
        raise HTTPException(422, "이미지를 읽지 못했어요. 정상적인 JPG, PNG, WebP 파일을 선택해 주세요.") from None
