from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

from groq import Groq

from app.config import settings

_log = logging.getLogger(__name__)

GROQ_MODEL = "llama-3.1-8b-instant"

_PROMPT_PREFIX = """You are parsing a job application email.
Return JSON only, no other text, no markdown.
{
  company: string or null,
  role: string or null,
  status: one of exactly:
    Applied, Rejected, Interview, OA, Offer, Unknown,
  confidence: integer 0-100
}
Rules:
- Only return Applied if email confirms person
  submitted an application, not if recruiter reached out
- Extract company from email body not sender domain
- If role not in body, extract from subject line
- If company is null, infer employer name from the subject when it clearly appears
  (e.g. "Engineer | Acme Inc", "Role at Acme", "Acme — Software Engineer")
- If genuinely uncertain return Unknown with low confidence

Email subject: """

_PROMPT_SUBJECT_BODY_SEP = """
Email body: """


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

    prompt = f"{_PROMPT_PREFIX}{subject}{_PROMPT_SUBJECT_BODY_SEP}{body}"
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

    company = obj.get("company")
    if company is not None and not isinstance(company, str):
        company = str(company)
    role = obj.get("role")
    if role is not None and not isinstance(role, str):
        role = str(role)
    status_raw = obj.get("status")
    status = str(status_raw) if status_raw is not None else "Unknown"
    conf_raw = obj.get("confidence", 0)
    try:
        confidence = int(conf_raw)
    except (TypeError, ValueError):
        confidence = 0
    confidence = max(0, min(100, confidence))

    del obj

    return {
        "company": company,
        "role": role,
        "status": status,
        "confidence": confidence,
    }
