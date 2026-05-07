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
from app.models.application import Application, ApplicationStatus
from app.models.user import User
from app.services.gmail_client import build_user_credentials, _ensure_fresh_credentials
from app.services.normalize import normalize_label

_log = logging.getLogger(__name__)

TAB = "Applications"
RANGE_HEADERS = f"{TAB}!A10:D10"
RANGE_DATA = f"{TAB}!A11:D10000"
# Rebuild should wipe everything below the stats rows (keeps A2:F3).
RANGE_REBUILD_CLEAR = f"{TAB}!A4:F10000"
# Memory: only scan first 200 data rows when matching company+role (upsert / delete).
RANGE_MATCH_SLICE = f"{TAB}!A11:D200"
RANGE_ROW_COUNT_SLICE = f"{TAB}!A11:A500"

# Stats block: row 2 labels, row 3 formulas (A–F); data from row 11; headers row 10.
STATS_VALUE_RANGE = f"{TAB}!A2:F3"


def _hex_to_color(rgb_hex: str) -> dict[str, float]:
    h = rgb_hex.lstrip("#")
    return {
        "red": int(h[0:2], 16) / 255.0,
        "green": int(h[2:4], 16) / 255.0,
        "blue": int(h[4:6], 16) / 255.0,
    }


STATUS_CELL_BACKGROUND: dict[str, dict[str, float]] = {
    ApplicationStatus.APPLIED.value: _hex_to_color("#cfe2ff"),
    ApplicationStatus.INTERVIEW.value: _hex_to_color("#fff3cd"),
    ApplicationStatus.OA.value: _hex_to_color("#e8d5ff"),
    ApplicationStatus.REJECTED.value: _hex_to_color("#ffd7d7"),
    ApplicationStatus.OFFER.value: _hex_to_color("#d4edda"),
}


def effective_sheet_id(user: User) -> str | None:
    custom = (user.google_sheet_id or "").strip()
    if custom:
        return custom
    env_id = (settings.google_sheet_id or "").strip()
    return env_id or None


def _sheets_service(creds: Credentials):
    creds = _ensure_fresh_credentials(creds)
    return build("sheets", "v4", credentials=creds, cache_discovery=False)


def _stats_already_seeded(service, spreadsheet_id: str) -> bool:
    """True when A2 is the horizontal stats header (do not overwrite rows 2–3)."""
    try:
        res = (
            service.spreadsheets()
            .values()
            .get(spreadsheetId=spreadsheet_id, range=f"{TAB}!A2")
            .execute()
        )
        rows = res.get("values") or []
        if not rows or not rows[0]:
            return False
        return str(rows[0][0]).strip() == "Total Applied"
    except HttpError:
        return False


def _stats_format_requests(tab_id: int) -> list[dict]:
    grey = _hex_to_color("#f0f0f0")
    return [
        {
            "repeatCell": {
                "range": {
                    "sheetId": tab_id,
                    "startRowIndex": 1,
                    "endRowIndex": 2,
                    "startColumnIndex": 0,
                    "endColumnIndex": 6,
                },
                "cell": {
                    "userEnteredFormat": {
                        "backgroundColor": grey,
                        "textFormat": {"bold": True},
                    }
                },
                "fields": "userEnteredFormat(backgroundColor,textFormat.bold)",
            }
        },
        {
            "repeatCell": {
                "range": {
                    "sheetId": tab_id,
                    "startRowIndex": 2,
                    "endRowIndex": 3,
                    "startColumnIndex": 0,
                    "endColumnIndex": 6,
                },
                "cell": {
                    "userEnteredFormat": {
                        "textFormat": {"bold": True, "fontSize": 12},
                    }
                },
                "fields": "userEnteredFormat.textFormat",
            }
        },
    ]


def _header_format_requests(tab_id: int) -> list[dict]:
    """Force the row-10 header styling (prevents D10 being colored like a status cell)."""
    grey = _hex_to_color("#f0f0f0")
    return [
        {
            "repeatCell": {
                "range": {
                    "sheetId": tab_id,
                    # Row 10 in Sheets is 0-based index 9
                    "startRowIndex": 9,
                    "endRowIndex": 10,
                    "startColumnIndex": 0,
                    "endColumnIndex": 4,
                },
                "cell": {
                    "userEnteredFormat": {
                        "backgroundColor": grey,
                        "textFormat": {"bold": True},
                    }
                },
                "fields": "userEnteredFormat(backgroundColor,textFormat.bold)",
            }
        }
    ]


def _stats_headers_and_formulas() -> tuple[list[str], list[str]]:
    headers = [
        "Total Applied",
        "Interviews",
        "Online Assessment",
        "Rejected",
        "Offers",
        "Response Rate",
    ]
    # Lock ranges with INDIRECT so references never drift.
    # Also exclude header-like rows by requiring col A not blank and not equal "Date".
    formulas = [
        '=COUNTIFS(INDIRECT("A11:A1000"),"<>",INDIRECT("A11:A1000"),"<>Date",INDIRECT("D11:D1000"),"*Applied*")'
        '+COUNTIFS(INDIRECT("A11:A1000"),"<>",INDIRECT("A11:A1000"),"<>Date",INDIRECT("D11:D1000"),"*Interview*")'
        '+COUNTIFS(INDIRECT("A11:A1000"),"<>",INDIRECT("A11:A1000"),"<>Date",INDIRECT("D11:D1000"),"*OA*")'
        '+COUNTIFS(INDIRECT("A11:A1000"),"<>",INDIRECT("A11:A1000"),"<>Date",INDIRECT("D11:D1000"),"*Rejected*")'
        '+COUNTIFS(INDIRECT("A11:A1000"),"<>",INDIRECT("A11:A1000"),"<>Date",INDIRECT("D11:D1000"),"*Offer*")',
        '=COUNTIFS(INDIRECT("A11:A1000"),"<>",INDIRECT("A11:A1000"),"<>Date",INDIRECT("D11:D1000"),"*Interview*")',
        '=COUNTIFS(INDIRECT("A11:A1000"),"<>",INDIRECT("A11:A1000"),"<>Date",INDIRECT("D11:D1000"),"*OA*")',
        '=COUNTIFS(INDIRECT("A11:A1000"),"<>",INDIRECT("A11:A1000"),"<>Date",INDIRECT("D11:D1000"),"*Rejected*")',
        '=COUNTIFS(INDIRECT("A11:A1000"),"<>",INDIRECT("A11:A1000"),"<>Date",INDIRECT("D11:D1000"),"*Offer*")',
        '=IF(A3=0,"0%",TEXT((B3+C3+D3+E3)/A3,"0%"))',
    ]
    return headers, formulas


def ensure_stats_and_headers(service, spreadsheet_id: str) -> None:
    """Ensure stats headers/formulas and row-10 headers are present and valid."""
    tab_id = _tab_sheet_id(service, spreadsheet_id, TAB)
    if tab_id is None:
        return
    was_seeded = _stats_already_seeded(service, spreadsheet_id)

    # Rewrite formulas every run so accidental manual edits cannot break the stats block.
    stats_headers, stats_formulas = _stats_headers_and_formulas()

    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=f"{TAB}!A2:F2",
        valueInputOption="USER_ENTERED",
        body={"values": [stats_headers]},
    ).execute()

    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=f"{TAB}!A3:F3",
        valueInputOption="USER_ENTERED",
        body={"values": [stats_formulas]},
    ).execute()

    headers_body = {"values": [["Date", "Company", "Role", "Status"]]}
    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=RANGE_HEADERS,
        valueInputOption="USER_ENTERED",
        body=headers_body,
    ).execute()

    # Always enforce header style so "Status" header cannot be colored like a status value.
    reqs: list[dict] = []
    reqs.extend(_header_format_requests(tab_id))
    if not was_seeded:
        reqs.extend(_stats_format_requests(tab_id))
    if reqs:
        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": reqs},
        ).execute()


def _read_match_rows(service, spreadsheet_id: str) -> list[list[str]]:
    """Bounded read for row matching; caller should ``del`` the list when done."""
    try:
        res = service.spreadsheets().values().get(spreadsheetId=spreadsheet_id, range=RANGE_MATCH_SLICE).execute()
    except HttpError:
        return []
    rows = res.get("values") or []
    del res
    return rows


def _tab_sheet_id(service, spreadsheet_id: str, title: str) -> int | None:
    meta = service.spreadsheets().get(spreadsheetId=spreadsheet_id, fields="sheets(properties(sheetId,title))").execute()
    for sheet in meta.get("sheets", []):
        props = sheet.get("properties") or {}
        if props.get("title") == title:
            sid = props.get("sheetId")
            return int(sid) if sid is not None else None
    return None


def _date_cell(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.date().isoformat()


def _data_row_count(service, spreadsheet_id: str) -> int:
    """Approximate data height from column A up to 500 rows (memory cap)."""
    try:
        res = (
            service.spreadsheets()
            .values()
            .get(spreadsheetId=spreadsheet_id, range=RANGE_ROW_COUNT_SLICE)
            .execute()
        )
    except HttpError:
        return 0
    values = res.get("values") or []
    del res
    n = 0
    for i, row in enumerate(values):
        if row and any(str(c).strip() for c in row):
            n = i + 1
    del values
    return n


def sort_sheet_by_date(user: User) -> None:
    """Sort data rows 11+ by column A (date) descending."""
    sheet_id = effective_sheet_id(user)
    if not sheet_id or not user.google_refresh_token:
        return
    try:
        creds = build_user_credentials(user)
        service = _sheets_service(creds)
        tab_id = _tab_sheet_id(service, sheet_id, TAB)
        if tab_id is None:
            return
        n = _data_row_count(service, sheet_id)
        if n < 2:
            return
        service.spreadsheets().batchUpdate(
            spreadsheetId=sheet_id,
            body={
                "requests": [
                    {
                        "sortRange": {
                            "range": {
                                "sheetId": tab_id,
                                "startRowIndex": 10,
                                "endRowIndex": 10 + n,
                                "startColumnIndex": 0,
                                "endColumnIndex": 4,
                            },
                            "sortSpecs": [{"dimensionIndex": 0, "sortOrder": "DESCENDING"}],
                        }
                    }
                ]
            },
        ).execute()
    except HttpError as exc:
        _log.warning("Sheets sort failed for user %s: %s", user.id, exc)
    except Exception:
        _log.warning("Sheets sort unexpected error for user %s", user.id, exc_info=True)


def _apply_status_cell_color(
    service,
    spreadsheet_id: str,
    tab_id: int,
    row_1based: int,
    status_value: str,
) -> None:
    bg = STATUS_CELL_BACKGROUND.get(status_value, _hex_to_color("#ffffff"))
    service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={
            "requests": [
                {
                    "repeatCell": {
                        "range": {
                            "sheetId": tab_id,
                            "startRowIndex": row_1based - 1,
                            "endRowIndex": row_1based,
                            "startColumnIndex": 3,
                            "endColumnIndex": 4,
                        },
                        "cell": {"userEnteredFormat": {"backgroundColor": bg}},
                        "fields": "userEnteredFormat.backgroundColor",
                    }
                }
            ]
        },
    ).execute()


def _find_match_row(
    rows: list[list[str]], want_c: str, want_r: str
) -> int | None:
    for i, row in enumerate(rows):
        if len(row) < 3:
            continue
        b = row[1] if len(row) > 1 else ""
        c = row[2] if len(row) > 2 else ""
        if normalize_label(b) == want_c and normalize_label(c) == want_r:
            return 11 + i
    return None


def upsert_application_row(user: User, application: Application) -> None:
    sheet_id = effective_sheet_id(user)
    if not sheet_id or not user.google_refresh_token:
        return
    try:
        creds = build_user_credentials(user)
        service = _sheets_service(creds)
        ensure_stats_and_headers(service, sheet_id)
        tab_id = _tab_sheet_id(service, sheet_id, TAB)
        if tab_id is None:
            return

        rows = _read_match_rows(service, sheet_id)
        want_c = normalize_label(application.company)
        want_r = normalize_label(application.role)
        match_row = _find_match_row(rows, want_c, want_r)
        del rows

        date_s = _date_cell(application.email_date)
        status_s = application.status.value

        if match_row is not None:
            service.spreadsheets().values().update(
                spreadsheetId=sheet_id,
                range=f"{TAB}!A{match_row}:D{match_row}",
                valueInputOption="USER_ENTERED",
                body={"values": [[date_s, application.company, application.role, status_s]]},
            ).execute()
            _apply_status_cell_color(service, sheet_id, tab_id, match_row, status_s)
        else:
            new_row = [date_s, application.company, application.role, status_s]
            service.spreadsheets().values().append(
                spreadsheetId=sheet_id,
                range=f"{TAB}!A11",
                valueInputOption="USER_ENTERED",
                insertDataOption="INSERT_ROWS",
                body={"values": [new_row]},
            ).execute()
            rows_after = _read_match_rows(service, sheet_id)
            new_match = _find_match_row(rows_after, want_c, want_r)
            del rows_after
            if new_match is not None:
                _apply_status_cell_color(service, sheet_id, tab_id, new_match, status_s)

        _log.info("Sheets: wrote %s - %s - %s", application.company, application.role, status_s)
    except HttpError as exc:
        _log.warning("Sheets API failed for user %s: %s", user.id, exc)
    except Exception:
        _log.warning("Sheets sync unexpected error for user %s", user.id, exc_info=True)


def delete_application_row(user: User, company: str, role: str) -> None:
    """Remove the data row whose company+role (normalized) match; no-op if sheet unset or row missing."""
    sheet_id = effective_sheet_id(user)
    if not sheet_id or not user.google_refresh_token:
        return
    try:
        creds = build_user_credentials(user)
        service = _sheets_service(creds)
        ensure_stats_and_headers(service, sheet_id)
        tab_id = _tab_sheet_id(service, sheet_id, TAB)
        if tab_id is None:
            return
        rows = _read_match_rows(service, sheet_id)
        want_c = normalize_label(company)
        want_r = normalize_label(role)
        for i, row in enumerate(rows):
            if len(row) < 3:
                continue
            b = row[1] if len(row) > 1 else ""
            c = row[2] if len(row) > 2 else ""
            if normalize_label(b) == want_c and normalize_label(c) == want_r:
                row_1based = 11 + i
                start_idx = row_1based - 1
                service.spreadsheets().batchUpdate(
                    spreadsheetId=sheet_id,
                    body={
                        "requests": [
                            {
                                "deleteDimension": {
                                    "range": {
                                        "sheetId": tab_id,
                                        "dimension": "ROWS",
                                        "startIndex": start_idx,
                                        "endIndex": start_idx + 1,
                                    }
                                }
                            }
                        ]
                    },
                ).execute()
                del rows
                _log.info("Sheets: deleted row for %s - %s", company, role)
                return
        del rows
    except HttpError as exc:
        _log.warning("Sheets delete failed for user %s: %s", user.id, exc)
    except Exception:
        _log.warning("Sheets delete unexpected error for user %s", user.id, exc_info=True)


def rebuild_sheet(db: Session, user: User) -> int:
    sheet_id = effective_sheet_id(user)
    if not sheet_id:
        raise ValueError("No Google Sheet configured")
    if not user.google_refresh_token:
        raise ValueError("Google account not connected")

    creds = build_user_credentials(user)
    service = _sheets_service(creds)

    try:
        # Wipe everything below the stats block so stray headers/rows above A11
        # don't cause stats to "miss" items.
        service.spreadsheets().values().clear(spreadsheetId=sheet_id, range=RANGE_REBUILD_CLEAR).execute()
    except HttpError as exc:
        _log.warning("Sheets clear failed: %s", exc)
        raise

    ensure_stats_and_headers(service, sheet_id)
    tab_id = _tab_sheet_id(service, sheet_id, TAB)
    if tab_id is None:
        raise ValueError("Applications tab not found")

    apps = list(
        db.scalars(
            select(Application)
            .where(Application.user_id == user.id)
            .order_by(Application.email_date.asc(), Application.id.asc())
        ).all()
    )
    if not apps:
        sort_sheet_by_date(user)
        return 0

    values = [[_date_cell(a.email_date), a.company, a.role, a.status.value] for a in apps]
    service.spreadsheets().values().update(
        spreadsheetId=sheet_id,
        range=f"{TAB}!A11",
        valueInputOption="USER_ENTERED",
        body={"values": values},
    ).execute()

    for i, a in enumerate(apps):
        row_1based = 11 + i
        _apply_status_cell_color(service, sheet_id, tab_id, row_1based, a.status.value)

    # Force stats formula refresh after bulk write to avoid stale/overwritten cells.
    _, stats_formulas = _stats_headers_and_formulas()
    service.spreadsheets().values().update(
        spreadsheetId=sheet_id,
        range=f"{TAB}!A3:F3",
        valueInputOption="USER_ENTERED",
        body={"values": [stats_formulas]},
    ).execute()

    sort_sheet_by_date(user)
    return len(values)
