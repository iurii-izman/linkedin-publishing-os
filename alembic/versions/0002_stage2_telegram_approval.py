"""Add external Telegram approval orchestration state.

Revision ID: 0002_stage2_telegram
Revises: 0001_stage1_vertical
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0002_stage2_telegram"
down_revision: str | None = "0001_stage1_vertical"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "external_approval_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("draft_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("revision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("revision_sha256", sa.String(64), nullable=False),
        sa.Column("approval_fingerprint", sa.String(64), nullable=False),
        sa.Column("channel", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("callback_token_hash", sa.String(64), nullable=False),
        sa.Column("telegram_owner_user_id", sa.BigInteger(), nullable=False),
        sa.Column("telegram_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("requested_by", sa.String(200), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column("decision_actor_id", sa.String(200)),
        sa.Column("decision", sa.String(32)),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
        sa.Column("invalidated_at", sa.DateTime(timezone=True)),
        sa.Column("invalidation_reason", sa.String(300)),
        sa.Column("message_external_id", sa.String(200)),
        sa.Column("approval_id", postgresql.UUID(as_uuid=True)),
        sa.Column("publication_id", postgresql.UUID(as_uuid=True)),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("decision_idempotency_key", sa.String(128)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('PENDING','APPROVED','REJECTED','EXPIRED','INVALIDATED','CONSUMED')",
            name="ck_external_approval_status",
        ),
        sa.CheckConstraint(
            "decision IS NULL OR decision IN ('APPROVE_AND_PUBLISH','REJECT')",
            name="ck_external_approval_decision",
        ),
        sa.CheckConstraint(
            "length(revision_sha256) = 64", name="ck_external_approval_revision_sha"
        ),
        sa.CheckConstraint(
            "length(approval_fingerprint) = 64",
            name="ck_external_approval_fingerprint",
        ),
        sa.CheckConstraint(
            "length(callback_token_hash) = 64",
            name="ck_external_approval_callback_hash",
        ),
        sa.ForeignKeyConstraint(["approval_id"], ["approvals.id"]),
        sa.ForeignKeyConstraint(["draft_id"], ["drafts.id"]),
        sa.ForeignKeyConstraint(["publication_id"], ["publications.id"]),
        sa.ForeignKeyConstraint(["revision_id"], ["post_revisions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("callback_token_hash"),
        sa.UniqueConstraint("decision_idempotency_key"),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_index(
        "ix_external_approval_requests_revision_id",
        "external_approval_requests",
        ["revision_id"],
    )
    op.create_index(
        "ix_external_approval_status_expiry",
        "external_approval_requests",
        ["status", "expires_at"],
    )
    op.create_index(
        "ix_external_approval_telegram_owner_chat",
        "external_approval_requests",
        ["telegram_owner_user_id", "telegram_chat_id"],
    )
    op.create_index(
        "uq_external_approval_pending_revision_channel",
        "external_approval_requests",
        ["revision_id", "channel"],
        unique=True,
        postgresql_where=sa.text("status = 'PENDING'"),
    )
    op.create_table(
        "telegram_deliveries",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("approval_request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("phase", sa.String(20), nullable=False),
        sa.Column("delivery_status", sa.String(20), nullable=False),
        sa.Column("message_external_id", sa.String(200)),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("edited_at", sa.DateTime(timezone=True)),
        sa.Column("safe_error_category", sa.String(100)),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "delivery_status IN ('SENT','FAILED')",
            name="ck_telegram_delivery_status",
        ),
        sa.CheckConstraint("attempts = 1", name="ck_telegram_delivery_single_attempt"),
        sa.ForeignKeyConstraint(["approval_request_id"], ["external_approval_requests.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key"),
        sa.UniqueConstraint(
            "approval_request_id",
            "phase",
            name="uq_telegram_delivery_request_phase",
        ),
    )


def downgrade() -> None:
    op.drop_table("telegram_deliveries")
    op.drop_index(
        "uq_external_approval_pending_revision_channel",
        table_name="external_approval_requests",
    )
    op.drop_index(
        "ix_external_approval_telegram_owner_chat",
        table_name="external_approval_requests",
    )
    op.drop_index(
        "ix_external_approval_status_expiry",
        table_name="external_approval_requests",
    )
    op.drop_index(
        "ix_external_approval_requests_revision_id",
        table_name="external_approval_requests",
    )
    op.drop_table("external_approval_requests")
