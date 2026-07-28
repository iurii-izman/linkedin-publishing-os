from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Any

CANONICALIZATION_VERSION = "utf8-exact-v1"


class PublicationStatus(StrEnum):
    PREPARED = "PREPARED"
    PUBLISHING = "PUBLISHING"
    PUBLISHED = "PUBLISHED"
    FAILED = "FAILED"
    PUBLISH_UNCERTAIN = "PUBLISH_UNCERTAIN"


class AttemptOutcome(StrEnum):
    STARTED = "STARTED"
    PUBLISHED = "PUBLISHED"
    FAILED = "FAILED"
    PUBLISH_UNCERTAIN = "PUBLISH_UNCERTAIN"


TERMINAL_PUBLICATION_STATUSES = frozenset(
    {
        PublicationStatus.PUBLISHED,
        PublicationStatus.FAILED,
        PublicationStatus.PUBLISH_UNCERTAIN,
    }
)

ALLOWED_TRANSITIONS = {
    PublicationStatus.PREPARED: frozenset({PublicationStatus.PUBLISHING}),
    PublicationStatus.PUBLISHING: frozenset(
        {
            PublicationStatus.PUBLISHED,
            PublicationStatus.FAILED,
            PublicationStatus.PUBLISH_UNCERTAIN,
        }
    ),
}


class DomainError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int,
        retryable: bool = False,
        publication_status: PublicationStatus | None = None,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.retryable = retryable
        self.publication_status = publication_status


def utc_text_sha256(text: str) -> str:
    """Hash the exact UTF-8 bytes; whitespace and line endings are significant."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def stable_fingerprint(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def approval_fingerprint(revision_id: str, text_sha256: str) -> str:
    return stable_fingerprint(
        {
            "canonicalization_version": CANONICALIZATION_VERSION,
            "revision_id": revision_id,
            "text_sha256": text_sha256,
        }
    )


def transition_publication(
    current: PublicationStatus, target: PublicationStatus
) -> PublicationStatus:
    if target not in ALLOWED_TRANSITIONS.get(current, frozenset()):
        raise DomainError(
            "INVALID_PUBLICATION_TRANSITION",
            f"Publication cannot transition from {current} to {target}",
            status_code=409,
            publication_status=current,
        )
    return target
