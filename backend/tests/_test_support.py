"""One isolated application/database for integration tests in any discovery order."""

import atexit
import os
from pathlib import Path
import shutil
import sys
import uuid
from unittest.mock import patch


TESTS_DIR = Path(__file__).resolve().parent
# Inherit Windows workspace ACLs; tempfile's private ACL can deny this process.
TEST_ROOT = TESTS_DIR / (".auth-tests-" + uuid.uuid4().hex)
TEST_ROOT.mkdir()
sys.path.insert(0, str(TESTS_DIR.parent))

with patch.dict(os.environ, {
    "DATA_DIR": str(TEST_ROOT),
    # 배포용 PostgreSQL에서도 확인할 때: TEST_DATABASE_URL=postgresql+psycopg://... (테스트마다 테이블을 지우고 다시 만든다)
    "DATABASE_URL": os.environ.get("TEST_DATABASE_URL") or "sqlite:///" + (TEST_ROOT / "test.sqlite").as_posix(),
    "SESSION_SECRET": "isolated-integration-test-secret",
    "DEV_LOGIN": "false",
    "PUBLIC_BASE_URL": "http://testserver",
    "KAKAO_REST_API_KEY": "",
    "KAKAO_CLIENT_SECRET": "",
    "NAVER_API_KEY": "",
    "TTS_PROVIDER": "local",
    "VIDEO_PROVIDER": "local",
    "S3GEN_TRAINING": "false",
    "VOICE_TARGET_SECONDS": "135",
}):
    from app import db
    from app.config import settings
    from app.main import app


def using_isolated_database() -> bool:
    """테스트가 지우고 다시 만드는 DB가 실제 데이터가 아닌지: SQLite면 이 폴더의 파일, PostgreSQL이면 이름에 test가 든 DB."""
    url = db.engine.url
    if url.get_backend_name() == "sqlite":
        return Path(url.database).resolve() == (TEST_ROOT / "test.sqlite").resolve()
    return "test" in (url.database or "")


def _cleanup():
    db.engine.dispose()
    assert TEST_ROOT.resolve().parent == TESTS_DIR
    shutil.rmtree(TEST_ROOT)


atexit.register(_cleanup)
