from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class SettingsOut(BaseModel):
    gmail_connected: bool
    sheet_id: str
    sheet_id_from_env: bool
    last_synced_at: Optional[datetime] = None
    gmail_sync_lookback_days: int = 31


class SheetIdUpdate(BaseModel):
    google_sheet_id: str


class RebuildSheetOut(BaseModel):
    ok: bool
    rows_written: int
