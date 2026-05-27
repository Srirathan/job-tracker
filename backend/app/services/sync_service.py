from __future__ import annotations

import gc
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.models.application import Application, ApplicationStatus
from app.models.seen_message import SeenMessageId
from app.models.user import User
from app.services import gmail_client
from app.services.groq_extract import extract_job_fields
from app.services.gmail_client import GmailDisconnectedError
from app.services.normalize import is_likely_same_role, is_same_recruitment_cycle, normalize_label
from app.services.sheets_sync import sort_sheet_by_date, upsert_application_row

_log = logging.getLogger(__name__)

_SYNC_BATCH_SIZE = 2
_SYNC_BATCH_PAUSE_SECONDS = 3

_ALLOWED_EXTRACT_STATUSES = {"Applied", "Rejected", "Interview", "OA", "Offer"}

_STATUS_MAP: dict[str, ApplicationStatus] = {
    "Applied": ApplicationStatus.APPLIED,
    "Rejected": ApplicationStatus.REJECTED,
    "Interview": ApplicationStatus.INTERVIEW,
    "OA": ApplicationStatus.OA,
    "Offer": ApplicationStatus.OFFER,
}

_STATUS_PRECEDENCE: dict[ApplicationStatus, int] = {
    ApplicationStatus.APPLIED: 1,
    ApplicationStatus.OA: 2,
    ApplicationStatus.INTERVIEW: 3,
    ApplicationStatus.OFFER: 4,
    ApplicationStatus.REJECTED: 5,
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
        if normalize_label(app.company) == norm_company and is_likely_same_role(app.role, norm_role):
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

    n_messages = len(message_ids)
    _log.info("Sync capped at %s emails this run", cap)
    _log.info(
        "Gmail query yielded %s message id(s); process %s at a time, %ss pause + gc between groups",
        n_messages,
        _SYNC_BATCH_SIZE,
        _SYNC_BATCH_PAUSE_SECONDS,
    )

    def process_fetched_message(
        msg_id: str,
        subject: str,
        body_in: str,
        received_at: datetime,
        sender_domain: str | None,
    ) -> None:
        nonlocal new, updated, skipped, sk_groq, sk_conf, sk_co, sk_st, sk_dup

        body = body_in
        parsed = extract_job_fields(subject, body, sender_domain=sender_domain)
        del body

        if parsed["confidence"] < 70:
            skipped += 1
            if parsed.get("_groq_failed"):
                sk_groq += 1
                _log.info("Skipped %s: Groq extraction failed", msg_id)
            else:
                sk_conf += 1
                db.add(
                    SeenMessageId(
                        user_id=user.id,
                        gmail_message_id=msg_id,
                        processed_at=datetime.now(timezone.utc),
                    )
                )
                db.commit()
                _log.info("Skipped %s: low confidence %s", msg_id, parsed["confidence"])
            return

        canon_status = _normalize_ai_status(parsed["status"])
        if canon_status == "Unknown" or canon_status not in _ALLOWED_EXTRACT_STATUSES:
            skipped += 1
            sk_st += 1
            db.add(
                SeenMessageId(
                    user_id=user.id,
                    gmail_message_id=msg_id,
                    processed_at=datetime.now(timezone.utc),
                )
            )
            db.commit()
            _log.info("Skipped %s: unknown status", msg_id)
            return

        company = (parsed["company"] or "").strip()
        if not company:
            company = (_company_from_subject(subject) or "").strip()
        if not company and sender_domain:
            company = sender_domain
            _log.info("Using sender domain as company fallback for %s: %s", msg_id, company)
        if not company:
            company = "Unknown Company"
            _log.info("Using placeholder company for %s", msg_id)

        role = (parsed["role"] or "").strip() or subject.strip() or "Unknown role"
        status = _STATUS_MAP[canon_status]

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
                db.add(
                    SeenMessageId(
                        user_id=user.id,
                        gmail_message_id=msg_id,
                        processed_at=datetime.now(timezone.utc),
                    )
                )
                db.commit()
                return
            current_precedence = _STATUS_PRECEDENCE.get(existing_gmail.status, 0)
            new_precedence = _STATUS_PRECEDENCE.get(status, 0)
            if new_precedence < current_precedence:
                skipped += 1
                sk_dup += 1
                db.add(
                    SeenMessageId(
                        user_id=user.id,
                        gmail_message_id=msg_id,
                        processed_at=datetime.now(timezone.utc),
                    )
                )
                db.commit()
                _log.info(
                    "Skipped status downgrade %s: %s → %s",
                    msg_id,
                    existing_gmail.status.value,
                    status.value,
                )
                return
            existing_gmail.company = company
            existing_gmail.role = role
            existing_gmail.status = status
            existing_gmail.email_date = received_at
            existing_gmail.updated_at = datetime.now(timezone.utc)
            db.add(
                SeenMessageId(
                    user_id=user.id,
                    gmail_message_id=msg_id,
                    processed_at=datetime.now(timezone.utc),
                )
            )
            db.add(existing_gmail)
            db.commit()
            db.refresh(existing_gmail)
            updated += 1
            _log.info("Updated (same Gmail id): %s - %s → %s", company, role, status.value)
            upsert_application_row(user, existing_gmail)
            gc.collect()
            return

        norm_c = normalize_label(company)
        norm_r = normalize_label(role)
        existing = _find_duplicate_application(
            db, user.id, norm_c, norm_r, reference_time=datetime.now(timezone.utc)
        )

        if existing:
            if existing.status == status:
                skipped += 1
                sk_dup += 1
                db.add(
                    SeenMessageId(
                        user_id=user.id,
                        gmail_message_id=msg_id,
                        processed_at=datetime.now(timezone.utc),
                    )
                )
                db.commit()
                return
            current_precedence = _STATUS_PRECEDENCE.get(existing.status, 0)
            new_precedence = _STATUS_PRECEDENCE.get(status, 0)
            if new_precedence < current_precedence:
                skipped += 1
                sk_dup += 1
                db.add(
                    SeenMessageId(
                        user_id=user.id,
                        gmail_message_id=msg_id,
                        processed_at=datetime.now(timezone.utc),
                    )
                )
                db.commit()
                _log.info(
                    "Skipped status downgrade %s: %s → %s",
                    msg_id,
                    existing.status.value,
                    status.value,
                )
                return
            existing.status = status
            existing.updated_at = datetime.now(timezone.utc)
            db.add(
                SeenMessageId(
                    user_id=user.id,
                    gmail_message_id=msg_id,
                    processed_at=datetime.now(timezone.utc),
                )
            )
            db.add(existing)
            db.commit()
            db.refresh(existing)
            updated += 1
            _log.info("Updated: %s - %s → %s", company, role, status.value)
            upsert_application_row(user, existing)
            gc.collect()
            return

        app = Application(
            user_id=user.id,
            gmail_message_id=msg_id,
            email_date=received_at,
            company=company,
            role=role,
            status=status,
        )
        db.add(
            SeenMessageId(
                user_id=user.id,
                gmail_message_id=msg_id,
                processed_at=datetime.now(timezone.utc),
            )
        )
        db.add(app)
        db.commit()
        db.refresh(app)
        new += 1
        _log.info("New application: %s - %s - %s", company, role, status.value)
        upsert_application_row(user, app)
        gc.collect()

    fetches_in_group = 0
    fetched_total = 0

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

        gm = gmail_client.fetch_message_for_sync(creds, msg_id)
        subject_in = gm.subject
        body_in = gm.body
        recv = gm.date
        sender_domain_in = gm.sender_domain
        del gm

        process_fetched_message(msg_id, subject_in, body_in, recv, sender_domain_in)

        del subject_in, body_in, recv

        fetches_in_group += 1
        fetched_total += 1

        if fetches_in_group >= _SYNC_BATCH_SIZE:
            gc.collect()
            _log.info(
                "Batch complete: %s email(s) fetched since last pause; scanned %s / %s id(s)",
                _SYNC_BATCH_SIZE,
                scanned,
                n_messages,
            )
            if scanned < n_messages:
                time.sleep(_SYNC_BATCH_PAUSE_SECONDS)
            fetches_in_group = 0

    if fetches_in_group > 0:
        gc.collect()

    user.last_synced_at = datetime.now(timezone.utc)
    db.add(user)
    db.commit()

    sort_sheet_by_date(user)

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


_jobs: dict[str, dict] = {}
_active_sync_users: set[int] = set()


def cleanup_old_jobs() -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
    to_remove: list[str] = []
    for job_id, job in _jobs.items():
        started_raw = job.get("started_at")
        if not started_raw:
            continue
        try:
            started = datetime.fromisoformat(str(started_raw).replace("Z", "+00:00"))
            if started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            continue
        if started < cutoff:
            to_remove.append(job_id)
    for job_id in to_remove:
        del _jobs[job_id]


def get_job_state(job_id: str) -> dict | None:
    return _jobs.get(job_id)


def run_gmail_sync_background(job_id: str, db_url: str, user_id: int) -> None:
    cleanup_old_jobs()
    started_at = _jobs.get(job_id, {}).get("started_at")
    if user_id in _active_sync_users:
        _jobs[job_id] = {
            "status": "error",
            "summary": None,
            "error": "A sync is already running for this account. Please wait.",
            "started_at": started_at,
            "finished_at": datetime.now(timezone.utc).isoformat(),
        }
        return
    _active_sync_users.add(user_id)
    engine = None
    db: Session | None = None
    try:
        connect_args = {"check_same_thread": False} if db_url.startswith("sqlite") else {}
        engine_kwargs: dict = {"connect_args": connect_args}
        if not db_url.startswith("sqlite"):
            engine_kwargs["pool_pre_ping"] = True
        engine = create_engine(db_url, **engine_kwargs)
        SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        db = SessionLocal()
        user = db.get(User, user_id)
        if user is None:
            raise ValueError("User not found")
        summary = run_gmail_sync(db, user)
        _jobs[job_id] = {
            "status": "done",
            "summary": summary,
            "error": None,
            "started_at": started_at,
            "finished_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        _log.exception("Background sync failed for job %s user %s", job_id, user_id)
        _jobs[job_id] = {
            "status": "error",
            "summary": None,
            "error": str(e),
            "started_at": started_at,
            "finished_at": datetime.now(timezone.utc).isoformat(),
        }
    finally:
        _active_sync_users.discard(user_id)
        if db is not None:
            db.close()
        if engine is not None:
            engine.dispose()
