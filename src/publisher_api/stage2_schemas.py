from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr


class ExternalApprovalRequestCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    requested_by: str = Field(default="owner", min_length=1, max_length=200)


class ExternalApprovalInvalidate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=1, max_length=300)


class TelegramPreviewResponse(BaseModel):
    request_id: uuid.UUID
    draft_title: str | None
    revision_number: int
    exact_text: str
    text_length: int
    revision_sha256_prefix: str
    expires_at: datetime
    actions: list[Literal["APPROVE_AND_PUBLISH", "REJECT"]]
    warning: str


class ExternalApprovalRequestResponse(BaseModel):
    id: uuid.UUID
    draft_id: uuid.UUID
    revision_id: uuid.UUID
    status: str
    channel: str
    revision_sha256_prefix: str
    approval_fingerprint: str
    expires_at: datetime
    decision: str | None
    approval_id: uuid.UUID | None
    publication_id: uuid.UUID | None
    callback_token: str | None = None
    replayed: bool = False
    preview: TelegramPreviewResponse | None = None


class ApprovalDecisionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    callback_token: SecretStr
    telegram_user_id: int
    telegram_chat_id: int
    decision: Literal["APPROVE_AND_PUBLISH", "REJECT"]
    callback_query_id: str = Field(min_length=1, max_length=200)
    message_external_id: str | None = Field(default=None, max_length=200)


class ApprovalDecisionResponse(BaseModel):
    request_id: uuid.UUID
    status: str
    decision: str
    approval_id: uuid.UUID | None
    publication_id: uuid.UUID | None
    next_action: Literal["PREPARE", "STOP", "GET_RESULT"]
    replayed: bool


class TelegramDeliveryResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    phase: Literal["PREVIEW", "RESULT"]
    delivery_status: Literal["SENT", "FAILED"]
    message_external_id: str | None = Field(default=None, max_length=200)
    safe_error_category: str | None = Field(default=None, max_length=100)


class OrchestrationPrepare(BaseModel):
    model_config = ConfigDict(extra="forbid")
    connection_id: uuid.UUID


class OrchestrationExecute(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approval_request_id: uuid.UUID
    confirm_execute: bool
