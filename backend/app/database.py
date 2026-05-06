import logging

from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import settings

_log = logging.getLogger(__name__)

connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}

engine = create_engine(settings.database_url, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def _sqlite_table_columns(conn, table: str) -> set[str]:
    rows = conn.execute(text(f"PRAGMA table_info({table})")).all()
    return {r[1] for r in rows}


def ensure_sqlite_schema() -> None:
    """SQLite: add columns introduced after first deploy (create_all does not ALTER)."""
    if not settings.database_url.startswith("sqlite"):
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
