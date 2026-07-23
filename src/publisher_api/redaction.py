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


def redact_text(value: str) -> str:
    value = _BEARER.sub(f"Bearer {REDACTED}", value)
    return _TOKENISH.sub(REDACTED, value)


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
