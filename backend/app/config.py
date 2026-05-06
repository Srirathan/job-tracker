from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Load only backend/.env (exact filename ".env") next to this package.
_BACKEND_DIR = Path(__file__).resolve().parent.parent
ENV_FILE_PATH = _BACKEND_DIR / ".env"


class Settings(BaseSettings):
    database_url: str = "sqlite:///./app.db"
    jwt_secret_key: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60

    # Gmail (read-only). OAuth "Web application" in Google Cloud Console.
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://127.0.0.1:8000/api/gmail/oauth/callback"
    frontend_url: str = "http://localhost:5173"

    google_sheet_id: str = ""

    gmail_sync_newer_than_days: int = 31

    gemini_api_key: str = ""
    # `gemini-1.5-flash` is no longer available on the current API; override via GEMINI_MODEL if needed.
    gemini_model: str = "gemini-2.5-flash"

    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE_PATH),
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
