from __future__ import annotations

import logging
from datetime import datetime, timezone

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models.application import Application
from app.models.user import User
from app.services.gmail_client import SCOPES, build_user_credentials, _ensure_fresh_credentials
from app.services.normalize import normalize_label

_log = logging.getLogger(__name__)

TAB = "Applications"
RANGE_STATS_ROWS = f"{TAB}!A2:D7"
RANGE_HEADERS = f"{TAB}!A10:D10"
RANGE_DATA = f"{TAB}!A11:D10000"


def effective_sheet_id(user: User) -> str | None:
    custom = (user.google_sheet_id or "").strip()
    if custom:
        return custom
    env_id = (settings.google_sheet_id or "").strip()
    return env_id or None


def _sheets_service(creds: Credentials):
    creds = _ensure_fresh_credentials(creds)
    return build("sheets", "v4", credentials=creds, cache_discovery=False)


def _stats_region_blank(service, spreadsheet_id: str) -> bool:
    """True when rows 2–7 (stats block) have no content — first sync can seed formulas."""
    try:
        res = service.spreadsheets().values().get(spreadsheetId=spreadsheet_id, range=RANGE_STATS_ROWS).execute()
    except HttpError:
        return False
    rows = res.get("values") or []
    for row in rows:
        for cell in row:
            if cell is not None and str(cell).strip():
                return False
    return True


def ensure_stats_and_headers(service, spreadsheet_id: str) -> None:
    """Write stats (rows 2–7) and headers (row 10) once if stats area is empty."""
    if not _stats_region_blank(service, spreadsheet_id):
        return
    stats_body = {
        "values": [
            ["", "", "", ""],
            ["Total Applied", '=COUNTIF(D11:D1000,"Applied")', "", ""],
            ["Interviews", '=COUNTIF(D11:D1000,"Interview")', "", ""],
            ["Online Assessment", '=COUNTIF(D11:D1000,"OA")', "", ""],
            ["Rejected", '=COUNTIF(D11:D1000,"Rejected")', "", ""],
            ["Offers", '=COUNTIF(D11:D1000,"Offer")', "", ""],
            ["Response Rate", '=IF(B2>0,(B3+B4+B5+B6)/B2,"")', "", ""],
        ]
    }
    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=f"{TAB}!A1:D7",
        valueInputOption="USER_ENTERED",
        body=stats_body,
    ).execute()

    headers_body = {"values": [["Date", "Company", "Role", "Status"]]}
    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=RANGE_HEADERS,
        valueInputOption="USER_ENTERED",
        body=headers_body,
    ).execute()


def _read_data_rows(service, spreadsheet_id: str) -> list[list[str]]:
    try:
        res = service.spreadsheets().values().get(spreadsheetId=spreadsheet_id, range=RANGE_DATA).execute()
    except HttpError:
        return []
    return res.get("values") or []


def _date_cell(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.date().isoformat()


def upsert_application_row(user: User, application: Application) -> None:
    sheet_id = effective_sheet_id(user)
    if not sheet_id or not user.google_refresh_token:
        return
    try:
        creds = build_user_credentials(user)
        service = _sheets_service(creds)
        ensure_stats_and_headers(service, sheet_id)
        rows = _read_data_rows(service, sheet_id)
        want_c = normalize_label(application.company)
        want_r = normalize_label(application.role)
        match_row: int | None = None
        for i, row in enumerate(rows):
            if len(row) < 3:
                continue
            b = row[1] if len(row) > 1 else ""
            c = row[2] if len(row) > 2 else ""
            if normalize_label(b) == want_c and normalize_label(c) == want_r:
                match_row = 11 + i
                break
        date_s = _date_cell(application.email_date)
        status_s = application.status.value
        if match_row is not None:
            service.spreadsheets().values().update(
                spreadsheetId=sheet_id,
                range=f"{TAB}!D{match_row}",
                valueInputOption="USER_ENTERED",
                body={"values": [[status_s]]},
            ).execute()
        else:
            new_row = [date_s, application.company, application.role, status_s]
            service.spreadsheets().values().append(
                spreadsheetId=sheet_id,
                range=f"{TAB}!A11",
                valueInputOption="USER_ENTERED",
                insertDataOption="INSERT_ROWS",
                body={"values": [new_row]},
            ).execute()
        _log.info("Sheets: wrote %s - %s - %s", application.company, application.role, status_s)
    except HttpError as exc:
        _log.warning("Sheets API failed for user %s: %s", user.id, exc)
    except Exception:
        _log.warning("Sheets sync unexpected error for user %s", user.id, exc_info=True)


def rebuild_sheet(db: Session, user: User) -> int:
    sheet_id = effective_sheet_id(user)
    if not sheet_id:
        raise ValueError("No Google Sheet configured")
    if not user.google_refresh_token:
        raise ValueError("Google account not connected")

    creds = build_user_credentials(user)
    service = _sheets_service(creds)

    try:
        service.spreadsheets().values().clear(spreadsheetId=sheet_id, range=RANGE_DATA).execute()
    except HttpError as exc:
        _log.warning("Sheets clear failed: %s", exc)
        raise

    ensure_stats_and_headers(service, sheet_id)

    apps = list(
        db.scalars(
            select(Application)
            .where(Application.user_id == user.id)
            .order_by(Application.email_date.asc(), Application.id.asc())
        ).all()
    )
    if not apps:
        return 0

    values = [
        [_date_cell(a.email_date), a.company, a.role, a.status.value] for a in apps
    ]
    service.spreadsheets().values().update(
        spreadsheetId=sheet_id,
        range=f"{TAB}!A11",
        valueInputOption="USER_ENTERED",
        body={"values": values},
    ).execute()
    return len(values)
