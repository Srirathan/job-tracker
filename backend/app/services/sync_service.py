from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models.application import Application, ApplicationStatus
from app.models.seen_message import SeenMessageId
from app.models.user import User
from app.services import gmail_client
from app.services.groq_extract import extract_job_fields
from app.services.gmail_client import GmailDisconnectedError
from app.services.normalize import is_same_recruitment_cycle, normalize_label
from app.services.sheets_sync import upsert_application_row

_log = logging.getLogger(__name__)

_ALLOWED_EXTRACT_STATUSES = {"Applied", "Rejected", "Interview", "OA", "Offer"}

_STATUS_MAP: dict[str, ApplicationStatus] = {
    "Applied": ApplicationStatus.APPLIED,
    "Rejected": ApplicationStatus.REJECTED,
    "Interview": ApplicationStatus.INTERVIEW,
    "OA": ApplicationStatus.OA,
    "Offer": ApplicationStatus.OFFER,
}


def _normalize_ai_status(raw: str) -> str:
    """Map common model variants to the five allowed status labels."""
    s = (raw or "").strip()
    if s in _ALLOWED_EXTRACT_STATUSES:
        return s
    sl = re.sub(r"\s+", " ", s.lower().strip('.,!?"\''))
    if sl in ("oa", "o.a.") or sl.startswith("online assessment"):
        return "OA"
    for hint in (
        "online assessment",
        "assessment invitation",
        "assessment link",
        "take-home",
        "take home",
        "hackerrank",
        "hacker rank",
        "codesignal",
        "codility",
        "coding assessment",
    ):
        if hint in sl:
            return "OA"
    if any(
        h in sl
        for h in (
            "rejected",
            "not selected",
            "not moving forward",
            "no longer under consideration",
            "unable to offer",
        )
    ):
        return "Rejected"
    if any(
        h in sl
        for h in (
            "phone screen",
            " interview",
            "interview ",
            "schedule an interview",
            "interview schedule",
            "invite you to interview",
        )
    ):
        return "Interview"
    if sl in ("offer", "job offer") or "offer of employment" in sl or "pleased to offer" in sl:
        return "Offer"
    if sl in (
        "applied",
        "application submitted",
        "application received",
        "submission confirmed",
        "confirmation of application",
    ):
        return "Applied"
    return s


def _company_from_subject(subject: str) -> str | None:
    if not (subject or "").strip():
        return None
    subj = subject.strip()
    for sep in (" at ", " @ ", " | ", " — ", " – ", " - "):
        lo = subj.lower()
        idx = lo.find(sep.lower())
        if idx >= 0:
            right = subj[idx + len(sep) :].strip()
            if 2 <= len(right) <= 200:
                return right.splitlines()[0].strip()
    return None


@dataclass
class SyncSummary:
    scanned: int
    new: int
    updated: int
    skipped: int
    skipped_already_seen: int
    skipped_groq_failed: int
    skipped_low_confidence: int
    skipped_missing_company: int
    skipped_unknown_status: int
    skipped_duplicate_same_status: int


def _find_duplicate_application(
    db: Session,
    user_id: int,
    norm_company: str,
    norm_role: str,
    *,
    reference_time: datetime,
) -> Application | None:
    """Same normalized company+role only counts as duplicate if within the recruitment cycle window."""
    ref = reference_time
    in_cycle: list[Application] = []
    for app in db.scalars(select(Application).where(Application.user_id == user_id)).all():
        if normalize_label(app.company) == norm_company and normalize_label(app.role) == norm_role:
            if is_same_recruitment_cycle(app.email_date, reference_time=ref):
                in_cycle.append(app)
    if not in_cycle:
        return None
    return max(in_cycle, key=lambda a: a.email_date)


def run_gmail_sync(db: Session, user: User) -> SyncSummary:
    scanned = new = updated = skipped = 0
    sk_seen = sk_groq = sk_conf = sk_co = sk_st = sk_dup = 0

    if not user.google_refresh_token:
        raise ValueError("Gmail not connected")

    try:
        lookback = max(1, min(int(settings.gmail_sync_newer_than_days), 120))
    except (TypeError, ValueError):
        lookback = 30
    _log.info("Sync started for user %s (Gmail lookback %s days)", user.id, lookback)

    creds = gmail_client.build_user_credentials(user)
    query = gmail_client.build_job_search_query()

    cap = settings.gmail_max_emails_per_sync
    try:
        message_ids = gmail_client.list_message_ids(creds, query, max_ids=cap)
    except GmailDisconnectedError:
        raise

    _log.info("Fetched %s Gmail message id(s) for this run (cap %s)", len(message_ids), cap)

    for msg_id in message_ids:
        scanned += 1
        seen = db.scalar(
            select(SeenMessageId).where(
                SeenMessageId.user_id == user.id,
                SeenMessageId.gmail_message_id == msg_id,
            )
        )
        if seen:
            skipped += 1
            sk_seen += 1
            _log.info("Skipped %s: already seen", msg_id)
            continue

        try:
            subject, body, received_at = gmail_client.get_message_plain_text_and_meta(creds, msg_id)
        except GmailDisconnectedError:
            raise

        body = body or ""

        db.add(
            SeenMessageId(
                user_id=user.id,
                gmail_message_id=msg_id,
                processed_at=datetime.now(timezone.utc),
            )
        )
        db.commit()

        parsed = extract_job_fields(subject, body)
        del body

        if parsed["confidence"] < 60:
            skipped += 1
            if parsed.get("_groq_failed"):
                sk_groq += 1
                _log.info("Skipped %s: Groq extraction failed", msg_id)
            else:
                sk_conf += 1
                _log.info("Skipped %s: low confidence %s", msg_id, parsed["confidence"])
            continue

        canon_status = _normalize_ai_status(parsed["status"])
        if canon_status == "Unknown" or canon_status not in _ALLOWED_EXTRACT_STATUSES:
            skipped += 1
            sk_st += 1
            _log.info("Skipped %s: unknown status", msg_id)
            continue

        company = (parsed["company"] or "").strip()
        if not company:
            company = (_company_from_subject(subject) or "").strip()
        if not company:
            skipped += 1
            sk_co += 1
            _log.info("Skipped %s: missing company", msg_id)
            continue

        role = (parsed["role"] or "").strip() or subject.strip() or "Unknown role"
        status = _STATUS_MAP[canon_status]

        # Same Gmail message must map to one row. Clearing seen_message_ids without deleting
        # applications would otherwise INSERT again and hit UNIQUE(user_id, gmail_message_id).
        existing_gmail = db.scalar(
            select(Application).where(
                Application.user_id == user.id,
                Application.gmail_message_id == msg_id,
            )
        )
        if existing_gmail is not None:
            unchanged = (
                existing_gmail.company == company
                and existing_gmail.role == role
                and existing_gmail.status == status
            )
            if unchanged:
                skipped += 1
                sk_dup += 1
                continue
            existing_gmail.company = company
            existing_gmail.role = role
            existing_gmail.status = status
            existing_gmail.email_date = received_at
            existing_gmail.updated_at = datetime.now(timezone.utc)
            db.add(existing_gmail)
            db.commit()
            db.refresh(existing_gmail)
            updated += 1
            _log.info("Updated (same Gmail id): %s - %s → %s", company, role, status.value)
            upsert_application_row(user, existing_gmail)
            continue

        norm_c = normalize_label(company)
        norm_r = normalize_label(role)
        existing = _find_duplicate_application(
            db, user.id, norm_c, norm_r, reference_time=datetime.now(timezone.utc)
        )

        if existing:
            if existing.status == status:
                skipped += 1
                sk_dup += 1
                continue
            existing.status = status
            existing.updated_at = datetime.now(timezone.utc)
            db.add(existing)
            db.commit()
            db.refresh(existing)
            updated += 1
            _log.info("Updated: %s - %s → %s", company, role, status.value)
            upsert_application_row(user, existing)
            continue

        app = Application(
            user_id=user.id,
            gmail_message_id=msg_id,
            email_date=received_at,
            company=company,
            role=role,
            status=status,
        )
        db.add(app)
        db.commit()
        db.refresh(app)
        new += 1
        _log.info("New application: %s - %s - %s", company, role, status.value)
        upsert_application_row(user, app)

    user.last_synced_at = datetime.now(timezone.utc)
    db.add(user)
    db.commit()

    return SyncSummary(
        scanned=scanned,
        new=new,
        updated=updated,
        skipped=skipped,
        skipped_already_seen=sk_seen,
        skipped_groq_failed=sk_groq,
        skipped_low_confidence=sk_conf,
        skipped_missing_company=sk_co,
        skipped_unknown_status=sk_st,
        skipped_duplicate_same_status=sk_dup,
    )
