from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from publisher_api.stage1_domain import AttemptOutcome, PublicationStatus

JsonType = JSON().with_variant(JSONB, "postgresql")


def utc_now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Draft(Base):
    __tablename__ = "drafts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str | None] = mapped_column(String(300))
    current_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("post_revisions.id", name="fk_drafts_current_revision", use_alter=True),
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PostRevision(Base):
    __tablename__ = "post_revisions"
    __table_args__ = (
        UniqueConstraint("draft_id", "revision_number", name="uq_revision_number"),
        CheckConstraint("revision_number > 0", name="ck_revision_number_positive"),
        CheckConstraint("length(text_sha256) = 64", name="ck_revision_sha256_length"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    draft_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("drafts.id"), nullable=False, index=True
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    text_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    canonicalization_version: Mapped[str] = mapped_column(String(32), nullable=False)
    supersedes_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("post_revisions.id")
    )
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Approval(Base):
    __tablename__ = "approvals"
    __table_args__ = (
        CheckConstraint("length(revision_sha256) = 64", name="ck_approval_sha256_length"),
        CheckConstraint("length(approval_fingerprint) = 64", name="ck_approval_fingerprint_length"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    revision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("post_revisions.id"), nullable=False, index=True
    )
    revision_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    approval_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    approved_by: Mapped[str] = mapped_column(String(200), nullable=False)
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revocation_reason: Mapped[str | None] = mapped_column(String(500))
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class LinkedInConnection(Base):
    __tablename__ = "linkedin_connections"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_subject: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    encrypted_access_token: Mapped[str] = mapped_column(Text, nullable=False)
    token_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    scopes: Mapped[list[str]] = mapped_column(JsonType, nullable=False)
    person_urn: Mapped[str] = mapped_column(String(300), nullable=False)
    token_metadata: Mapped[dict[str, Any]] = mapped_column(JsonType, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    last_validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Publication(Base):
    __tablename__ = "publications"
    __table_args__ = (
        UniqueConstraint("revision_id", "connection_id", name="uq_publication_destination"),
        CheckConstraint(
            "status IN ('PREPARED','PUBLISHING','PUBLISHED','FAILED','PUBLISH_UNCERTAIN')",
            name="ck_publication_status",
        ),
        CheckConstraint(
            "length(request_fingerprint) = 64", name="ck_publication_fingerprint_length"
        ),
        CheckConstraint(
            "(status <> 'PUBLISHED') OR linkedin_post_identifier IS NOT NULL",
            name="ck_published_identifier",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    draft_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("drafts.id"), nullable=False
    )
    revision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("post_revisions.id"), nullable=False
    )
    approval_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("approvals.id"), nullable=False
    )
    connection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("linkedin_connections.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=PublicationStatus.PREPARED.value, index=True
    )
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    linkedin_post_identifier: Mapped[str | None] = mapped_column(String(500))
    prepared_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_category: Mapped[str | None] = mapped_column(String(100))
    safe_error_code: Mapped[str | None] = mapped_column(String(100))
    safe_error_message: Mapped[str | None] = mapped_column(String(300))
    request_attempted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    response_received: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


Index(
    "ix_publications_stale",
    Publication.status,
    Publication.started_at,
    postgresql_where=Publication.status == PublicationStatus.PUBLISHING.value,
)


class PublicationAttempt(Base):
    __tablename__ = "publication_attempts"
    __table_args__ = (
        UniqueConstraint("publication_id", name="uq_one_attempt_per_publication"),
        CheckConstraint("attempt_number = 1", name="ck_stage1_single_attempt"),
        CheckConstraint(
            "outcome IN ('STARTED','PUBLISHED','FAILED','PUBLISH_UNCERTAIN')",
            name="ck_attempt_outcome",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    publication_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("publications.id"), nullable=False
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    stage: Mapped[str] = mapped_column(String(50), nullable=False, default="FINAL_POST")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    request_attempted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    response_received: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    http_status: Mapped[int | None] = mapped_column(Integer)
    outcome: Mapped[str] = mapped_column(
        String(32), nullable=False, default=AttemptOutcome.STARTED.value
    )
    safe_error_category: Mapped[str | None] = mapped_column(String(100))
    safe_error_code: Mapped[str | None] = mapped_column(String(100))
    safe_error_message: Mapped[str | None] = mapped_column(String(300))
    linkedin_post_identifier: Mapped[str | None] = mapped_column(String(500))


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    aggregate_type: Mapped[str] = mapped_column(String(50), nullable=False)
    aggregate_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(50), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(200), nullable=False)
    request_id: Mapped[str] = mapped_column(String(100), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    safe_metadata: Mapped[dict[str, Any]] = mapped_column(JsonType, nullable=False, default=dict)


Index(
    "ix_audit_aggregate",
    AuditEvent.aggregate_type,
    AuditEvent.aggregate_id,
    AuditEvent.occurred_at,
)


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (
        UniqueConstraint("scope", "idempotency_key", name="uq_idempotency_scope_key"),
        CheckConstraint(
            "length(request_fingerprint) = 64", name="ck_idempotency_fingerprint_length"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    scope: Mapped[str] = mapped_column(String(250), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(50), nullable=False)
    resource_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
