from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class DraftCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(default=None, max_length=300)


class DraftResponse(BaseModel):
    id: uuid.UUID
    title: str | None
    current_revision_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None


class RevisionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=3000)
    created_by: str = Field(min_length=1, max_length=200)


class RevisionResponse(BaseModel):
    id: uuid.UUID
    draft_id: uuid.UUID
    revision_number: int
    text: str
    text_sha256: str
    canonicalization_version: str
    supersedes_revision_id: uuid.UUID | None
    created_by: str
    created_at: datetime


class ApprovalCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approved_by: str = Field(min_length=1, max_length=200)


class ApprovalRevoke(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=1, max_length=500)


class ApprovalResponse(BaseModel):
    id: uuid.UUID
    revision_id: uuid.UUID
    revision_sha256: str
    approval_fingerprint: str
    approved_by: str
    approved_at: datetime
    revoked_at: datetime | None
    revocation_reason: str | None
    created_at: datetime


class PublicationPrepare(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision_id: uuid.UUID
    approval_id: uuid.UUID
    connection_id: uuid.UUID


class PublicationExecute(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm_execute: bool


class PublicationResponse(BaseModel):
    id: uuid.UUID
    draft_id: uuid.UUID
    revision_id: uuid.UUID
    approval_id: uuid.UUID
    connection_id: uuid.UUID
    status: str
    request_fingerprint: str
    linkedin_post_identifier_present: bool
    prepared_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    failure_category: str | None
    safe_error_code: str | None
    safe_error_message: str | None
    request_attempted: bool
    response_received: bool
    created_at: datetime
    updated_at: datetime


class AuditEventResponse(BaseModel):
    id: uuid.UUID
    aggregate_type: str
    aggregate_id: uuid.UUID
    event_type: str
    actor_type: str
    actor_id: str
    request_id: str
    occurred_at: datetime
    safe_metadata: dict[str, Any]


class ErrorResponse(BaseModel):
    code: str
    message: str
    request_id: str
    retryable: bool
    publication_status: str | None = None
