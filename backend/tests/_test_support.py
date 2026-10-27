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
    "DATABASE_URL": "sqlite:///" + (TEST_ROOT / "test.sqlite").as_posix(),
    "SESSION_SECRET": "isolated-integration-test-secret",
    "DEV_LOGIN": "false",
    "PUBLIC_BASE_URL": "http://testserver",
    "KAKAO_REST_API_KEY": "",
    "KAKAO_CLIENT_SECRET": "",
    "NAVER_API_KEY": "",
    "TTS_PROVIDER": "local",
    "VIDEO_PROVIDER": "local",
    "S3GEN_TRAINING": "false",
    "VOICE_TARGET_SECONDS": "90",
}):
    from app import db
    from app.config import settings
    from app.main import app


def _cleanup():
    db.engine.dispose()
    assert TEST_ROOT.resolve().parent == TESTS_DIR
    shutil.rmtree(TEST_ROOT)


atexit.register(_cleanup)
