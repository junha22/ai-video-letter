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
    # Existing SQLite tables need the new recipient index after ALTER TABLE.
    for table in Base.metadata.sorted_tables:
        for index in table.indexes:
            try:
                index.create(engine, checkfirst=True)
            except DBAPIError:
                # The API and worker can start together and create the same index.
                if index.name not in {item["name"] for item in inspect(engine).get_indexes(table.name)}:
                    raise
    from .services.conversations import backfill_recipient_data
    with SessionLocal() as db:
        backfill_recipient_data(db)


def _add_missing_columns() -> None:
    """create_all은 이미 있는 테이블에 새 칸을 넣지 않는다. 모델에 새로 생긴 칸을 ALTER TABLE로 추가한다 (개발용 간이 마이그레이션).
    기본값이 고정값이면 DEFAULT로 같이 넣어서 기존 행도 그 값을 갖는다.
    칸 이름 변경·삭제는 처리하지 않으므로 운영 DB로 옮길 때는 Alembic을 쓴다."""
    quote = engine.dialect.identifier_preparer.quote
    for table in Base.metadata.sorted_tables:
        existing = {c["name"] for c in inspect(engine).get_columns(table.name)}
        for col in table.columns:
            if col.name in existing:
                continue
            default = col.default.arg if col.default is not None and col.default.is_scalar else None
            ddl = f"ALTER TABLE {quote(table.name)} ADD COLUMN {quote(col.name)} {col.type.compile(engine.dialect)}"
            if isinstance(default, str):
                ddl += " DEFAULT '" + default.replace("'", "''") + "'"
            elif isinstance(default, (bool, int, float)):
                ddl += f" DEFAULT {int(default) if isinstance(default, bool) else default}"
            try:
                with engine.begin() as conn:
                    conn.execute(text(ddl))
            except DBAPIError:
                # API 서버와 워커가 동시에 시작하면 다른 쪽이 먼저 추가했을 수 있다
                if col.name not in {c["name"] for c in inspect(engine).get_columns(table.name)}:
                    raise
