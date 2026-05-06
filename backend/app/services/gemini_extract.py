from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any

from google.api_core import exceptions as google_api_exceptions

from app.config import settings

_log = logging.getLogger(__name__)

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


@dataclass
class GeminiExtractResult:
    company: str | None
    role: str | None
    status: str
    confidence: int


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


def _response_text(response: Any) -> str:
    """Handle normal text, safety blocks, and multi-part responses."""
    try:
        t = (response.text or "").strip()
        if t:
            return t
    except ValueError:
        pass
    candidates = getattr(response, "candidates", None) or []
    if not candidates:
        return ""
    parts = getattr(candidates[0].content, "parts", None) or []
    chunks: list[str] = []
    for p in parts:
        if getattr(p, "text", None):
            chunks.append(p.text)
    return "".join(chunks).strip()


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


def extract_job_fields(subject: str, body: str) -> GeminiExtractResult | None:
    if not (settings.gemini_api_key or "").strip():
        _log.warning("GEMINI_API_KEY missing; skipping AI extraction")
        return None

    try:
        import google.generativeai as genai
    except ImportError:
        _log.warning("google-generativeai not installed; skipping AI extraction")
        return None

    prompt = f"{_PROMPT_PREFIX}{subject}{_PROMPT_SUBJECT_BODY_SEP}{body}"
    genai.configure(api_key=settings.gemini_api_key)
    model_name = (settings.gemini_model or "gemini-2.5-flash").strip()
    model = genai.GenerativeModel(model_name)
    response = None
    for attempt in range(2):
        try:
            response = model.generate_content(prompt)
            break
        except google_api_exceptions.ResourceExhausted:
            if attempt == 0:
                _log.warning("Gemini rate limited; retrying once (model=%s)", model_name)
                time.sleep(2.5)
                continue
            _log.exception("Gemini quota exhausted (model=%s)", model_name)
            return None
        except Exception:
            _log.exception("Gemini API request failed (model=%s)", model_name)
            return None
    if response is None:
        return None

    text = _response_text(response)
    if not text:
        _log.warning("Gemini returned empty or blocked response (model=%s)", model_name)
        return None

    obj = _parse_json_object(text)
    if not obj:
        _log.warning("Gemini returned non-JSON output")
        return None

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

    return GeminiExtractResult(company=company, role=role, status=status, confidence=confidence)
