from contextlib import contextmanager

from sqlalchemy import create_engine, event, inspect, select, text
from sqlalchemy.orm import Session, sessionmaker

from core import config
from core.models import Base, Setting

_engine = None
_SessionLocal = None


def configure(url: str | None = None):
    """(Re)create the engine. Tests call this with an in-memory URL."""
    global _engine, _SessionLocal
    _engine = create_engine(url or config.DB_URL, future=True)

    @event.listens_for(_engine, "connect")
    def _fk_on(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)
    Base.metadata.create_all(_engine)
    _add_missing_columns(_engine)
    return _engine


def _add_missing_columns(engine):
    """Adds columns introduced after a database was created (create_all only makes new tables)."""
    insp = inspect(engine)
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            existing = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in existing:
                    continue
                ddl = f"ALTER TABLE {table.name} ADD COLUMN {col.name} {col.type.compile(engine.dialect)}"
                if col.server_default is not None:
                    ddl += f" DEFAULT '{col.server_default.arg}' NOT NULL"
                conn.execute(text(ddl))


def get_engine():
    if _engine is None:
        configure()
    return _engine


@contextmanager
def session_scope() -> Session:
    if _SessionLocal is None:
        configure()
    s = _SessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


DEFAULT_SETTINGS = {
    "alert_drop_pct": "5",
    "backup_dir": str(config.DEFAULT_BACKUP_DIR),
    "backup_keep": "8",
    "telegram_chat_id": "",
}


def get_setting(key: str) -> str:
    with session_scope() as s:
        row = s.get(Setting, key)
        return row.value if row else DEFAULT_SETTINGS.get(key, "")


def set_setting(key: str, value: str):
    with session_scope() as s:
        row = s.get(Setting, key)
        if row:
            row.value = str(value)
        else:
            s.add(Setting(key=key, value=str(value)))


def all_settings() -> dict:
    out = dict(DEFAULT_SETTINGS)
    with session_scope() as s:
        for row in s.scalars(select(Setting)):
            out[row.key] = row.value
    return out
