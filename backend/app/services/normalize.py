import html
import re
from datetime import datetime, timedelta, timezone

_STRIP_TOKENS = frozenset(
    {
        "inc",
        "ltd",
        "corp",
        "llc",
        "co",
        "company",
        "careers",
        "recruiting",
        "hr",
        "technologies",
        "technology",
        "tech",
        "solutions",
        "services",
        "global",
        "group",
        "holdings",
        "labs",
        "lab",
        "studio",
        "studios",
        "software",
        "systems",
        "platforms",
        "platform",
        "ai",
        "canada",
        "us",
        "usa",
        "north",
        "america",
    }
)

# When company+role match, merge only if the existing row is within this many days (same hiring cycle).
RECRUITMENT_CYCLE_DAYS = 180


def normalize_label(value: str) -> str:
    """Lowercase, drop punctuation, remove noise tokens and extra spaces."""
    s = html.unescape(value)
    s = s.lower()
    for sep in (" - ", " – ", " — ", " | "):
        s = s.replace(sep, " ")
    s = s.replace("&", "and")
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    if not s:
        return ""
    s = re.sub(r"\bswe\b", "software engineer", s)
    s = re.sub(r"\beng\b", "engineer", s)
    s = re.sub(r"\bsr\b", "senior", s)
    s = re.sub(r"\bjr\b", "junior", s)
    s = re.sub(r"\bco op\b", "coop", s)
    s = re.sub(r"\bcoop\b", "coop", s)
    parts = [w for w in s.split() if w not in _STRIP_TOKENS]
    return " ".join(parts)


def is_likely_same_role(raw_a: str, raw_b: str) -> bool:
    a = normalize_label(raw_a)
    b = normalize_label(raw_b)
    if a == b:
        return True
    if a and b and (a.startswith(b) or b.startswith(a)):
        return abs(len(a) - len(b)) <= 30
    return False


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
