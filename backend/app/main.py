import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import models  # noqa: F401
from app.config import ENV_FILE_PATH, settings
from app.database import Base, engine, ensure_sqlite_schema


def _allow_oauth_http_for_local_redirect() -> None:
    """oauthlib refuses HTTP token exchanges unless this is set; local dev uses http://127.0.0.1."""
    uri = (settings.google_redirect_uri or "").strip().lower()
    if uri.startswith("http://127.0.0.1") or uri.startswith("http://localhost"):
        os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")


_allow_oauth_http_for_local_redirect()
from app.routes.applications import router as applications_router
from app.routes.auth import router as auth_router
from app.routes.gmail import router as gmail_router
from app.routes.settings import router as settings_router
from app.routes.sync import router as sync_router
from app.services.gmail_client import gmail_oauth_configured

Base.metadata.create_all(bind=engine)
ensure_sqlite_schema()

_log = logging.getLogger("uvicorn.error")


@asynccontextmanager
async def lifespan(app: FastAPI):
    has_id = bool((settings.google_client_id or "").strip())
    has_secret = bool((settings.google_client_secret or "").strip())
    has_redirect = bool((settings.google_redirect_uri or "").strip())
    _log.info(
        "Gmail OAuth env: env_file_exists=%s client_id_present=%s client_secret_present=%s "
        "redirect_uri_present=%s gmail_oauth_configured=%s (loaded from: %s)",
        ENV_FILE_PATH.is_file(),
        has_id,
        has_secret,
        has_redirect,
        gmail_oauth_configured(),
        str(ENV_FILE_PATH),
    )
    yield


app = FastAPI(title="Job Tracker API", version="0.2.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(applications_router)
app.include_router(sync_router)
app.include_router(settings_router)
app.include_router(gmail_router)


@app.get("/health")
def health():
    return {"status": "ok"}
