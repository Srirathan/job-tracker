from datetime import date, datetime, timezone
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.application import ApplicationStatus


class SheetRowPairIn(BaseModel):
    company: str
    role: str


class SheetRowsSnapshotIn(BaseModel):
    """Remaining B/C pairs on the Applications sheet after a row removal (row 11+)."""

    spreadsheet_id: Optional[str] = None
    rows: list[SheetRowPairIn] = []
    #: When true and rows is empty, delete all applications for the sheet owner (no data rows left).
    confirm_empty: bool = False


class SheetWebhookUpdateIn(BaseModel):
    """Body from Google Apps Script on edits in the Applications data block (sheet row ≥ 11)."""

    row_number: int = Field(ge=1)
    company: str
    role: str
    status: str
    #: Optional column A date (YYYY-MM-DD). If omitted on create, server uses UTC “today”.
    date: Optional[datetime] = None
    #: Ownership filter — send SpreadsheetApp.getActiveSpreadsheet().getId() from the Script.
    spreadsheet_id: Optional[str] = None

    @field_validator("date", mode="before")
    @classmethod
    def coerce_sheet_date(cls, v: object) -> object:
        if v is None or v == "":
            return None
        return _coerce_app_date(v)


class ApplicationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: int
    user_id: int
    gmail_message_id: Optional[str] = None
    date: datetime = Field(validation_alias="email_date")
    company: str
    role: str
    status: ApplicationStatus
    created_at: datetime
    updated_at: datetime


def _coerce_app_date(v: object) -> datetime:
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if isinstance(v, date):
        return datetime.combine(v, datetime.min.time(), tzinfo=timezone.utc)
    if isinstance(v, str):
        s = v.strip()
        return datetime.combine(date.fromisoformat(s[:10]), datetime.min.time(), tzinfo=timezone.utc)
    raise TypeError("Invalid date value")


class ApplicationUpsertIn(BaseModel):
    company: str = Field(min_length=1, max_length=512)
    role: str = Field(min_length=1, max_length=512)
    status: ApplicationStatus
    date: datetime

    @field_validator("date", mode="before")
    @classmethod
    def coerce_date(cls, v: object) -> datetime:
        if v is None:
            raise ValueError("date required")
        return _coerce_app_date(v)
