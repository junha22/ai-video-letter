"""사진 검사: 정면 얼굴 1명, 해상도, 밝기, 흐림."""

import io
from dataclasses import dataclass, field

import cv2
import numpy as np
from PIL import Image, ImageOps

MIN_SIDE = 480
MAX_SIDE = 1280


def _load_cascade() -> "cv2.CascadeClassifier":
    # 경로에 한글이 있으면 OpenCV가 파일을 못 읽어서 메모리로 읽는다
    path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    with open(path, encoding="utf-8") as f:
        storage = cv2.FileStorage(f.read(), cv2.FILE_STORAGE_READ | cv2.FILE_STORAGE_MEMORY)
    cascade = cv2.CascadeClassifier()
    cascade.read(storage.getFirstTopLevelNode())
    return cascade


_cascade = _load_cascade()


@dataclass
class PhotoCheck:
    image: Image.Image | None = None
    face: list[int] | None = None  # 저장할 이미지 기준 [x, y, w, h]
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


def check(data: bytes) -> PhotoCheck:
    result = PhotoCheck()
    try:
        img = Image.open(io.BytesIO(data))
        img = ImageOps.exif_transpose(img).convert("RGB")
    except Exception:
        result.problems.append("사진 파일을 열 수 없어요. JPG나 PNG 사진을 올려 주세요.")
        return result

    if min(img.size) < MIN_SIDE:
        result.problems.append(f"사진 해상도가 낮아요. 가로·세로 {MIN_SIDE}픽셀 이상인 사진을 올려 주세요.")
        return result

    scale = min(1.0, MAX_SIDE / max(img.size))
    if scale < 1.0:
        img = img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)
    result.image = img

    gray = cv2.cvtColor(np.asarray(img), cv2.COLOR_RGB2GRAY)
    min_face = int(min(gray.shape) * 0.12)
    faces = _cascade.detectMultiScale(
        cv2.equalizeHist(gray), scaleFactor=1.1, minNeighbors=6, minSize=(min_face, min_face)
    )
    faces = sorted((tuple(int(v) for v in f) for f in faces), key=lambda f: f[2] * f[3], reverse=True)

    if not faces:
        result.problems.append("얼굴을 찾지 못했어요. 정면을 바라보고 찍은 사진을 올려 주세요.")
        return result
    if len(faces) > 1 and faces[1][2] * faces[1][3] > 0.3 * faces[0][2] * faces[0][3]:
        result.problems.append("여러 사람이 나온 사진이에요. 혼자 나온 사진을 올려 주세요.")
        return result

    x, y, w, h = faces[0]
    result.face = [x, y, w, h]
    if w < img.width * 0.18:
        result.problems.append("얼굴이 너무 작게 나왔어요. 얼굴이 크게 보이도록 가까이서 찍어 주세요.")

    region = gray[y : y + h, x : x + w]
    brightness = float(region.mean())
    if brightness < 70:
        result.problems.append("얼굴이 어둡게 나왔어요. 밝은 곳에서 찍은 사진을 올려 주세요.")
    elif brightness > 210:
        result.problems.append("빛이 너무 강해서 얼굴이 하얗게 나왔어요. 다른 사진을 올려 주세요.")
    if float(cv2.Laplacian(region, cv2.CV_64F).var()) < 40:
        result.problems.append("사진이 흐려요. 초점이 맞은 선명한 사진을 올려 주세요.")
    return result
