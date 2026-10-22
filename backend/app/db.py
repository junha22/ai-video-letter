from collections.abc import Iterator
from datetime import datetime, timezone

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings

_is_sqlite = settings.database_url.startswith("sqlite")
if _is_sqlite:
    settings.data_dir.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False, "timeout": 15} if _is_sqlite else {},
)

if _is_sqlite:

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _record):
        # 웹 서버와 워커가 동시에 쓰기 때문에 WAL 모드로 연다
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=15000")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()


SessionLocal = sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def iso(dt: datetime | None) -> str | None:
    return dt.isoformat() + "Z" if dt else None


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from . import models  # noqa: F401  테이블 등록

    Base.metadata.create_all(engine)
    _add_missing_columns()


def _add_missing_columns() -> None:
    """create_all은 이미 있는 테이블에 새 칸을 넣지 않는다. 비워 둬도 되는(nullable) 새 칸만 ALTER TABLE로 추가한다.
    칸 이름 변경·삭제나 NOT NULL 칸 추가가 필요해지면 Alembic으로 옮긴다."""
    quote = engine.dialect.identifier_preparer.quote
    for table in Base.metadata.sorted_tables:
        existing = {c["name"] for c in inspect(engine).get_columns(table.name)}
        for col in table.columns:
            if col.name in existing or not col.nullable:
                continue
            ddl = f"ALTER TABLE {quote(table.name)} ADD COLUMN {quote(col.name)} {col.type.compile(engine.dialect)}"
            try:
                with engine.begin() as conn:
                    conn.execute(text(ddl))
            except DBAPIError:
                # API 서버와 워커가 동시에 시작하면 다른 쪽이 먼저 추가했을 수 있다
                if col.name not in {c["name"] for c in inspect(engine).get_columns(table.name)}:
                    raise
