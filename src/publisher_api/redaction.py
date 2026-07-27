from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit, urlunsplit

REDACTED = "[REDACTED]"
_SENSITIVE_KEY = re.compile(
    r"(access[_-]?token|refresh[_-]?token|client[_-]?secret|authorization|auth[_-]?code)",
    re.IGNORECASE,
)
_BEARER = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_TOKENISH = re.compile(r"\b(?:AQ|eyJ)[A-Za-z0-9._~+/=-]{20,}\b")
_EMBEDDED_URL = re.compile(r"https?://[^\s\"'<>]+")
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(client[_-]?secret|encryption[_-]?key|authorization[_-]?code|oauth[_-]?state)"
    r"\s*[:=]\s*[^\s,;]+"
)
_LINKEDIN_URN = re.compile(r"\burn:li:(?:person|image|share|ugcPost):[A-Za-z0-9_-]+\b")
_LONG_OPAQUE = re.compile(r"(?<![A-Za-z0-9])[A-Za-z0-9_-]{32,}(?![A-Za-z0-9])")


def redact_text(value: str) -> str:
    value = _BEARER.sub(f"Bearer {REDACTED}", value)
    value = _TOKENISH.sub(REDACTED, value)
    value = _SECRET_ASSIGNMENT.sub(lambda match: f"{match.group(1)}={REDACTED}", value)
    value = _LINKEDIN_URN.sub(REDACTED, value)
    value = _EMBEDDED_URL.sub(lambda match: _redact_embedded_url(match.group(0)), value)
    return _LONG_OPAQUE.sub(REDACTED, value)


def _redact_embedded_url(value: str) -> str:
    parts = urlsplit(value)
    if parts.hostname == "www.linkedin.com" and parts.path.startswith("/dms-uploads/"):
        return REDACTED
    return redact_url(value)


def redact_url(value: str) -> str:
    parts = urlsplit(value)
    if not parts.query:
        return value
    return urlunsplit((parts.scheme, parts.netloc, parts.path, REDACTED, ""))


def redact(value: Any, key: str | None = None) -> Any:
    if key is not None and _SENSITIVE_KEY.search(key):
        return REDACTED
    if isinstance(value, str):
        if value.startswith(("http://", "https://")):
            return redact_text(redact_url(value))
        return redact_text(value)
    if isinstance(value, Mapping):
        return {
            str(item_key): redact(item_value, str(item_key))
            for item_key, item_value in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact(item) for item in value)
    return value
