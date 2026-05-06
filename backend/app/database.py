import logging

from sqlalchemy import create_engine, text
from sqlalchemy.engine.url import make_url
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import settings

_log = logging.getLogger(__name__)


def _redact_database_url(url: str) -> str:
    try:
        return make_url(url).render_as_string(hide_password=True)
    except Exception:
        return "<could not parse DATABASE_URL; check format>"


def _is_sqlite_url(url: str) -> bool:
    try:
        driver = make_url(url).drivername.split("+", 1)[0]
        return driver == "sqlite"
    except Exception:
        return url.strip().lower().startswith("sqlite")


def _create_engine_with_logging():
    url = settings.database_url
    # SQLite (any path): FastAPI + SQLAlchemy use multiple threads; this avoids thread errors.
    connect_args = {"check_same_thread": False} if _is_sqlite_url(url) else {}
    engine_kwargs: dict = {"connect_args": connect_args}
    if not _is_sqlite_url(url):
        engine_kwargs["pool_pre_ping"] = True

    safe_url = _redact_database_url(url)
    try:
        return create_engine(url, **engine_kwargs)
    except ModuleNotFoundError as exc:
        _log.exception(
            "Database engine: missing Python driver (%s). URL=%s.",
            exc,
            safe_url,
        )
        raise
    except Exception:
        _log.exception(
            "Database engine: create_engine failed. URL=%s. Check path, permissions, and URL format.",
            safe_url,
        )
        raise


engine = _create_engine_with_logging()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def _sqlite_table_columns(conn, table: str) -> set[str]:
    rows = conn.execute(text(f"PRAGMA table_info({table})")).all()
    return {r[1] for r in rows}


def ensure_sqlite_schema() -> None:
    """SQLite: add columns introduced after first deploy (create_all does not ALTER)."""
    if not _is_sqlite_url(settings.database_url):
        return
    with engine.begin() as conn:
        try:
            user_cols = _sqlite_table_columns(conn, "users")
        except Exception as exc:
            _log.warning("SQLite schema check skipped (users): %s", type(exc).__name__)
            return

        if "google_refresh_token" not in user_cols:
            conn.execute(text("ALTER TABLE users ADD COLUMN google_refresh_token TEXT"))
            _log.info("SQLite schema: added users.google_refresh_token")
        if "last_synced_at" not in user_cols:
            conn.execute(text("ALTER TABLE users ADD COLUMN last_synced_at DATETIME"))
            _log.info("SQLite schema: added users.last_synced_at")
        if "google_sheet_id" not in user_cols:
            conn.execute(text("ALTER TABLE users ADD COLUMN google_sheet_id VARCHAR(255)"))
            _log.info("SQLite schema: added users.google_sheet_id")
