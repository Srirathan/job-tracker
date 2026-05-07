from pathlib import Path

from pydantic import field_validator
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

    groq_api_key: str = ""
    groq_delay_seconds: int = 2

    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE_PATH),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("database_url", mode="before")
    @classmethod
    def normalize_database_url(cls, v: object) -> str:
        if v is None or (isinstance(v, str) and not str(v).strip()):
            return "sqlite:///./app.db"
        return str(v).strip()

    @field_validator("jwt_secret_key", mode="before")
    @classmethod
    def jwt_secret_non_empty(cls, v: object) -> str:
        if v is None or (isinstance(v, str) and not str(v).strip()):
            return "change-me-in-production"
        return str(v)

    @field_validator("access_token_expire_minutes", mode="before")
    @classmethod
    def token_minutes_coerce(cls, v: object) -> object:
        if v is None or v == "":
            return 60
        return v

    @field_validator("gmail_sync_newer_than_days", mode="before")
    @classmethod
    def lookback_days_coerce(cls, v: object) -> object:
        if v is None or v == "":
            return 31
        return v

    @field_validator("frontend_url", mode="before")
    @classmethod
    def frontend_url_absolute(cls, v: object) -> str:
        """Must include a scheme. Host-only values break OAuth redirect (browser treats them as relative paths)."""
        if v is None or (isinstance(v, str) and not str(v).strip()):
            return "http://localhost:5173"
        s = str(v).strip().rstrip("/")
        if "://" in s:
            return s
        low = s.lower()
        if low.startswith("localhost") or low.startswith("127.0.0.1"):
            return f"http://{s}"
        return f"https://{s}"

    @field_validator("groq_delay_seconds", mode="before")
    @classmethod
    def groq_delay_coerce(cls, v: object) -> object:
        if v is None or v == "":
            return 2
        return v


settings = Settings()
if settings.database_url.startswith("postgres://"):
    settings.database_url = settings.database_url.replace("postgres://", "postgresql://", 1)
