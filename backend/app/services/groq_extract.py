from __future__ import annotations

import html
import json
import logging
import re
import time
from typing import Any

from groq import Groq

from app.config import settings

_log = logging.getLogger(__name__)

GROQ_MODEL = "llama-3.1-8b-instant"

_PROMPT_TEMPLATE = """You are a strict parser for job application emails.
Return JSON only. No markdown, no explanation, no extra text.

{{
  "company": string or null,
  "role": string or null,
  "status": "Applied" | "Rejected" | "Interview" | "OA" | "Offer" | "Unknown",
  "confidence": integer 0-100
}}

Rules for company:
- Extract the HIRING company name only. Short and clean, e.g. "Google", "Shopify", "BDO".
- Do NOT include suffixes like Inc, LLC, Ltd, Corp, Canada, Technologies, Platforms.
- Do NOT copy example names from instructions.
- If you cannot identify the hiring company with confidence, return null.

Rules for role:
- Extract the specific job title only, e.g. "Software Engineer Intern", "Data Analyst Co-op".
- Maximum 80 characters. If longer, truncate to the core title.
- Do NOT use the email subject line as the role unless it contains only a job title.
- Do NOT include application IDs, dates, or tracking codes in the role.
- If you cannot identify a specific role, return null.

Rules for status:
- Applied: email confirms the person submitted an application.
- Interview: email invites to phone screen, interview, or scheduling link.
- OA: email contains a coding assessment, HackerRank, Codility, or take-home link.
- Offer: email explicitly offers employment.
- Rejected: email says not moving forward, not selected, or position filled.
- Unknown: anything else including recruiter outreach, newsletters, job alerts,
  project platforms, or emails where you are not certain.

Rules for confidence:
- 90-100: clear job application email with obvious company, role, and status.
- 70-89: mostly clear but one field required inference.
- 50-69: significant uncertainty in at least one field.
- 0-49: guessing, recruiter spam, newsletters, or non-application email.
- Return 0 if company is null or status is Unknown.

Email subject: {subject}
Email body: {body}"""

_COMPANY_BAD_SUBSTRINGS = (
    "apply",
    "application",
    "your ",
    "thank",
    "noreply",
    "no-reply",
    "unsubscribe",
    "click here",
    "dear ",
    "hello ",
)

_ROLE_BAD_SUBSTRINGS = (
    "new message from",
    "unsubscribe",
    "click here",
    "noreply",
    "you've been",
    "dear ",
    "hello ",
)


def _strip_code_fence(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        lines = t.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        t = "\n".join(lines).strip()
    return t


def _parse_json_object(text: str) -> dict[str, Any] | None:
    t = _strip_code_fence(text)
    try:
        obj = json.loads(t)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", t)
        if not m:
            return None
        try:
            obj = json.loads(m.group(0))
            return obj if isinstance(obj, dict) else None
        except json.JSONDecodeError:
            return None


def _sanitize_extracted(obj: dict[str, Any]) -> dict[str, Any]:
    company = obj.get("company")
    if company is not None and not isinstance(company, str):
        company = str(company)
    if company is not None:
        company = company.strip()
        if not company:
            company = None
        elif len(company) > 100:
            company = None
        else:
            cl = company.lower()
            if any(bad in cl for bad in _COMPANY_BAD_SUBSTRINGS):
                company = None

    role = obj.get("role")
    if role is not None and not isinstance(role, str):
        role = str(role)
    if role is not None:
        role = html.unescape(role).strip()
        if not role:
            role = None
        else:
            rl = role.lower()
            if any(bad in rl for bad in _ROLE_BAD_SUBSTRINGS):
                role = None
            elif len(role) > 80:
                truncated = role[:80]
                last_space = truncated.rfind(" ")
                role = truncated[:last_space].strip() if last_space > 0 else truncated.strip()

    status_raw = obj.get("status")
    status = str(status_raw) if status_raw is not None else "Unknown"

    conf_raw = obj.get("confidence", 0)
    try:
        confidence = int(conf_raw)
    except (TypeError, ValueError):
        confidence = 0

    if company is None:
        confidence = min(confidence, 30)
    if role is None:
        confidence = min(confidence, 40)
    if status == "Unknown":
        confidence = min(confidence, 20)
    confidence = max(0, min(100, confidence))

    return {
        "company": company,
        "role": role,
        "status": status,
        "confidence": confidence,
    }


def _unknown_zero(groq_failed: bool = False) -> dict[str, Any]:
    d: dict[str, Any] = {
        "company": None,
        "role": None,
        "status": "Unknown",
        "confidence": 0,
    }
    if groq_failed:
        d["_groq_failed"] = True
    return d


def _sleep_between_calls() -> None:
    time.sleep(max(0, settings.groq_delay_seconds))


def extract_job_fields(subject: str, body: str) -> dict[str, Any]:
    if not (settings.groq_api_key or "").strip():
        _log.warning("GROQ_API_KEY missing; returning Unknown with confidence 0")
        return _unknown_zero(groq_failed=False)

    prompt = _PROMPT_TEMPLATE.format(subject=subject, body=body)
    client: Groq | None = None
    text = ""
    try:
        client = Groq(api_key=settings.groq_api_key)
        try:
            response = client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
            )
        except Exception:
            _log.exception("Groq API request failed (model=%s); retrying once", GROQ_MODEL)
            time.sleep(max(0, settings.groq_delay_seconds))
            response = client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
            )
        text = ((response.choices[0].message.content or "").strip())
        del response
    except Exception:
        _log.exception("Groq API request failed (model=%s)", GROQ_MODEL)
        _sleep_between_calls()
        return _unknown_zero(groq_failed=True)
    finally:
        del prompt
        if client is not None:
            del client

    _sleep_between_calls()

    if not text:
        _log.warning("Groq returned empty response (model=%s)", GROQ_MODEL)
        return _unknown_zero(groq_failed=True)

    obj = _parse_json_object(text)
    del text
    if not obj:
        _log.warning("Groq returned non-JSON output")
        return _unknown_zero(groq_failed=True)

    cleaned = _sanitize_extracted(obj)
    del obj

    return cleaned
