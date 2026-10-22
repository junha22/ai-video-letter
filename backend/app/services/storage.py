"""로컬 파일 저장소. DB에는 data_dir 기준 상대 경로를 저장해서 나중에 S3 키로 바꾸기 쉽게 한다."""

import shutil
from pathlib import Path

from ..config import settings


def abs_path(rel: str) -> Path:
    return settings.data_dir / rel


def rel_path(path: Path) -> str:
    return path.relative_to(settings.data_dir).as_posix()


def user_dir(user_id: int, *parts: str) -> Path:
    path = settings.data_dir.joinpath("users", str(user_id), *parts)
    path.mkdir(parents=True, exist_ok=True)
    return path


def message_dir(user_id: int, message_id: int) -> Path:
    return user_dir(user_id, "messages", str(message_id))


def delete_tree(path: Path) -> int:
    """폴더를 지우고 지운 파일 수를 돌려준다."""
    if not path.exists():
        return 0
    count = sum(1 for p in path.rglob("*") if p.is_file())
    shutil.rmtree(path, ignore_errors=True)
    return count


def delete_file(rel: str | None) -> None:
    if rel:
        abs_path(rel).unlink(missing_ok=True)
