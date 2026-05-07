from __future__ import annotations

import base64
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parseaddr, parsedate_to_datetime
from html import unescape
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.config import settings
from app.models.user import User

_log = logging.getLogger(__name__)

MAX_PLAIN_BODY_CHARS = 300

SCOPES: list[str] = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/spreadsheets",
]

JOB_KEYWORDS = [
    "application received",
    "thank you for applying",
    "your application",
    "application status",
    "unfortunately",
    "interview",
    "assessment",
    "offer",
    "we regret",
    "not moving forward",
    "next steps",
    "congratulations",
]


class GmailDisconnectedError(Exception):
    """Raised when Gmail returns 401 (refresh token revoked or expired)."""


@dataclass(slots=True)
class GmailMessageSyncFields:
    """Minimal fields returned after fetch (no retained raw Gmail API blob)."""

    id: str
    subject: str
    body: str
    date: datetime
    sender: str


def gmail_oauth_configured() -> bool:
    return bool(
        (settings.google_client_id or "").strip()
        and (settings.google_client_secret or "").strip()
        and (settings.google_redirect_uri or "").strip()
    )


def build_user_credentials(user: User) -> Credentials:
    if not user.google_refresh_token:
        raise ValueError("Google account not connected")
    return Credentials(
        token=None,
        refresh_token=user.google_refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        scopes=SCOPES,
    )


def _ensure_fresh_credentials(creds: Credentials) -> Credentials:
    if creds.expired or not creds.token:
        creds.refresh(Request())
    return creds


def build_job_search_query() -> str:
    """Uses GMAIL_SYNC_NEWER_THAN_DAYS from settings (clamped 1–120)."""
    try:
        days = int(settings.gmail_sync_newer_than_days)
    except (TypeError, ValueError):
        days = 30
    days = max(1, min(days, 120))
    parts = [f'"{phrase}"' for phrase in JOB_KEYWORDS]
    _log.debug("Gmail search newer_than:%sd", days)
    return f"newer_than:{days}d ({' OR '.join(parts)})"


def _decode_body_data(data: str) -> str:
    pad = "=" * (-len(data) % 4)
    raw = base64.urlsafe_b64decode((data + pad).encode("ascii"))
    return raw.decode("utf-8", errors="replace")


def _collect_plain_parts(payload: dict[str, Any], out: list[str]) -> None:
    mime = payload.get("mimeType") or ""
    body = payload.get("body") or {}
    data = body.get("data")
    if mime == "text/plain" and data:
        out.append(_decode_body_data(data))
    for part in payload.get("parts") or []:
        _collect_plain_parts(part, out)


def _collect_html_parts(payload: dict[str, Any], out: list[str]) -> None:
    mime = payload.get("mimeType") or ""
    body = payload.get("body") or {}
    data = body.get("data")
    if mime == "text/html" and data:
        out.append(_decode_body_data(data))
    for part in payload.get("parts") or []:
        _collect_html_parts(part, out)


def _html_to_plain(html: str) -> str:
    """Strip tags for AI extraction when there is no text/plain part (common for marketing emails)."""
    text = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", html)
    text = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _header(headers: list[dict[str, str]], name: str) -> str | None:
    want = name.lower()
    for h in headers:
        if (h.get("name") or "").lower() == want:
            return h.get("value")
    return None


def list_message_ids(creds: Credentials, query: str, *, max_ids: int | None = None) -> list[str]:
    """List message IDs (newest batches first); stop paging when ``max_ids`` reached."""
    creds = _ensure_fresh_credentials(creds)
    service = build("gmail", "v1", credentials=creds, cache_discovery=False)
    ids: list[str] = []
    page_token: str | None = None
    try:
        while True:
            req = (
                service.users().messages().list(userId="me", q=query, pageToken=page_token, maxResults=100)
            )
            resp = req.execute()
            del req
            for m in resp.get("messages") or []:
                mid = m.get("id")
                if mid:
                    ids.append(mid)
                    if max_ids is not None and len(ids) >= max_ids:
                        del resp
                        return ids
            page_token = resp.get("nextPageToken")
            del resp
            if not page_token:
                break
    except HttpError as exc:
        if exc.resp is not None and exc.resp.status == 401:
            raise GmailDisconnectedError from exc
        raise
    return ids


def fetch_message_for_sync(creds: Credentials, message_id: str) -> GmailMessageSyncFields:
    """
    Fetch one message, extract id / subject / body (truncated) / date / sender,
    discard the raw API response payload before returning.
    """
    creds = _ensure_fresh_credentials(creds)
    service = build("gmail", "v1", credentials=creds, cache_discovery=False)
    try:
        raw = (
            service.users()
            .messages()
            .get(userId="me", id=message_id, format="full")
            .execute()
        )
    except HttpError as exc:
        if exc.resp is not None and exc.resp.status == 401:
            raise GmailDisconnectedError from exc
        raise

    resolved_id = str(raw.get("id") or message_id)
    internal_top = raw.get("internalDate")
    payload = raw.get("payload") or {}
    del raw

    headers = payload.get("headers") or []
    subject = _header(headers, "Subject") or ""

    from_val = _header(headers, "From") or ""
    name_addr = parseaddr(from_val)
    sender = (name_addr[1] or name_addr[0] or "").strip()

    date_hdr = _header(headers, "Date")
    if date_hdr:
        try:
            received_at = parsedate_to_datetime(date_hdr)
            if received_at.tzinfo is None:
                received_at = received_at.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError, OverflowError):
            received_at = datetime.now(timezone.utc)
    else:
        internal = int(internal_top) if internal_top else 0
        if internal:
            received_at = datetime.fromtimestamp(internal / 1000.0, tz=timezone.utc)
        else:
            received_at = datetime.now(timezone.utc)

    del headers

    bodies: list[str] = []
    _collect_plain_parts(payload, bodies)
    plain = "\n".join(bodies).strip()
    del bodies
    if not plain:
        html_parts: list[str] = []
        _collect_html_parts(payload, html_parts)
        if html_parts:
            plain = _html_to_plain("\n".join(html_parts))
        del html_parts

    del payload

    if len(plain) > MAX_PLAIN_BODY_CHARS:
        plain = plain[:MAX_PLAIN_BODY_CHARS]

    return GmailMessageSyncFields(
        id=resolved_id,
        subject=subject,
        body=plain,
        date=received_at,
        sender=sender,
    )


def get_message_plain_text_and_meta(creds: Credentials, message_id: str) -> tuple[str, str, datetime]:
    """Backward-compatible shortcut: subject, plain_body (truncated to 500), received_at."""
    g = fetch_message_for_sync(creds, message_id)
    return g.subject, g.body, g.date
