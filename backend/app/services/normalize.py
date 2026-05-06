import re
from datetime import datetime, timedelta, timezone

_STRIP_TOKENS = frozenset({"inc", "ltd", "corp", "careers", "recruiting", "hr"})

# When company+role match, merge only if the existing row is within this many days (same hiring cycle).
RECRUITMENT_CYCLE_DAYS = 180


def normalize_label(value: str) -> str:
    """Lowercase, drop punctuation, remove noise tokens and extra spaces."""
    s = value.lower()
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    if not s:
        return ""
    parts = [w for w in s.split() if w not in _STRIP_TOKENS]
    return " ".join(parts)


def _ensure_aware_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def is_same_recruitment_cycle(
    existing_event_date: datetime,
    *,
    reference_time: datetime | None = None,
) -> bool:
    """
    True if an existing application (by email_date) is still in the same recruitment cycle
    as reference_time: event_date is on or after (reference_time - RECRUITMENT_CYCLE_DAYS).

    If older, treat company+role match as a new application cycle → allow a new row.
    """
    ref = reference_time or datetime.now(timezone.utc)
    ref = _ensure_aware_utc(ref)
    ev = _ensure_aware_utc(existing_event_date)
    cutoff = ref - timedelta(days=RECRUITMENT_CYCLE_DAYS)
    return ev >= cutoff
