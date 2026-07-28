"""Create the Stage 1 vertical publishing schema.

Revision ID: 0001_stage1_vertical
Revises:
Create Date: 2026-07-27
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0001_stage1_vertical"
down_revision = None
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.create_table(
        "drafts",
        sa.Column("id", UUID, nullable=False),
        sa.Column("title", sa.String(length=300), nullable=True),
        sa.Column("current_revision_id", UUID, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_drafts_current_revision_id", "drafts", ["current_revision_id"])

    op.create_table(
        "post_revisions",
        sa.Column("id", UUID, nullable=False),
        sa.Column("draft_id", UUID, nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("text_sha256", sa.String(length=64), nullable=False),
        sa.Column("canonicalization_version", sa.String(length=32), nullable=False),
        sa.Column("supersedes_revision_id", UUID, nullable=True),
        sa.Column("created_by", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("revision_number > 0", name="ck_revision_number_positive"),
        sa.CheckConstraint("length(text_sha256) = 64", name="ck_revision_sha256_length"),
        sa.ForeignKeyConstraint(["draft_id"], ["drafts.id"], name="fk_revision_draft"),
        sa.ForeignKeyConstraint(
            ["supersedes_revision_id"],
            ["post_revisions.id"],
            name="fk_revision_supersedes",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("draft_id", "revision_number", name="uq_revision_number"),
    )
    op.create_index("ix_post_revisions_draft_id", "post_revisions", ["draft_id"])
    op.create_foreign_key(
        "fk_drafts_current_revision",
        "drafts",
        "post_revisions",
        ["current_revision_id"],
        ["id"],
    )

    op.create_table(
        "approvals",
        sa.Column("id", UUID, nullable=False),
        sa.Column("revision_id", UUID, nullable=False),
        sa.Column("revision_sha256", sa.String(length=64), nullable=False),
        sa.Column("approval_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("approved_by", sa.String(length=200), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revocation_reason", sa.String(length=500), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("length(revision_sha256) = 64", name="ck_approval_sha256_length"),
        sa.CheckConstraint(
            "length(approval_fingerprint) = 64",
            name="ck_approval_fingerprint_length",
        ),
        sa.ForeignKeyConstraint(
            ["revision_id"], ["post_revisions.id"], name="fk_approval_revision"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("approval_fingerprint", name="uq_approval_fingerprint"),
        sa.UniqueConstraint("idempotency_key", name="uq_approval_idempotency_key"),
    )
    op.create_index("ix_approvals_revision_id", "approvals", ["revision_id"])

    op.create_table(
        "linkedin_connections",
        sa.Column("id", UUID, nullable=False),
        sa.Column("owner_subject", sa.String(length=200), nullable=False),
        sa.Column("encrypted_access_token", sa.Text(), nullable=False),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("scopes", JSONB, nullable=False),
        sa.Column("person_urn", sa.String(length=300), nullable=False),
        sa.Column("token_metadata", JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_validated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_subject", name="uq_linkedin_connection_owner"),
    )

    op.create_table(
        "publications",
        sa.Column("id", UUID, nullable=False),
        sa.Column("draft_id", UUID, nullable=False),
        sa.Column("revision_id", UUID, nullable=False),
        sa.Column("approval_id", UUID, nullable=False),
        sa.Column("connection_id", UUID, nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("linkedin_post_identifier", sa.String(length=500), nullable=True),
        sa.Column("prepared_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_category", sa.String(length=100), nullable=True),
        sa.Column("safe_error_code", sa.String(length=100), nullable=True),
        sa.Column("safe_error_message", sa.String(length=300), nullable=True),
        sa.Column("request_attempted", sa.Boolean(), nullable=False),
        sa.Column("response_received", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('PREPARED','PUBLISHING','PUBLISHED','FAILED','PUBLISH_UNCERTAIN')",
            name="ck_publication_status",
        ),
        sa.CheckConstraint(
            "length(request_fingerprint) = 64",
            name="ck_publication_fingerprint_length",
        ),
        sa.CheckConstraint(
            "(status <> 'PUBLISHED') OR linkedin_post_identifier IS NOT NULL",
            name="ck_published_identifier",
        ),
        sa.ForeignKeyConstraint(["approval_id"], ["approvals.id"], name="fk_publication_approval"),
        sa.ForeignKeyConstraint(
            ["connection_id"],
            ["linkedin_connections.id"],
            name="fk_publication_connection",
        ),
        sa.ForeignKeyConstraint(["draft_id"], ["drafts.id"], name="fk_publication_draft"),
        sa.ForeignKeyConstraint(
            ["revision_id"],
            ["post_revisions.id"],
            name="fk_publication_revision",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_publication_idempotency_key"),
        sa.UniqueConstraint(
            "revision_id",
            "connection_id",
            name="uq_publication_destination",
        ),
    )
    op.create_index("ix_publications_status", "publications", ["status"])
    op.create_index("ix_publications_started_at", "publications", ["started_at"])
    op.create_index(
        "ix_publications_stale",
        "publications",
        ["status", "started_at"],
        postgresql_where=sa.text("status = 'PUBLISHING'"),
    )

    op.create_table(
        "publication_attempts",
        sa.Column("id", UUID, nullable=False),
        sa.Column("publication_id", UUID, nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("stage", sa.String(length=50), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("request_attempted", sa.Boolean(), nullable=False),
        sa.Column("response_received", sa.Boolean(), nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("safe_error_category", sa.String(length=100), nullable=True),
        sa.Column("safe_error_code", sa.String(length=100), nullable=True),
        sa.Column("safe_error_message", sa.String(length=300), nullable=True),
        sa.Column("linkedin_post_identifier", sa.String(length=500), nullable=True),
        sa.CheckConstraint("attempt_number = 1", name="ck_stage1_single_attempt"),
        sa.CheckConstraint(
            "outcome IN ('STARTED','PUBLISHED','FAILED','PUBLISH_UNCERTAIN')",
            name="ck_attempt_outcome",
        ),
        sa.ForeignKeyConstraint(
            ["publication_id"],
            ["publications.id"],
            name="fk_attempt_publication",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("publication_id", name="uq_one_attempt_per_publication"),
    )

    op.create_table(
        "audit_events",
        sa.Column("id", UUID, nullable=False),
        sa.Column("aggregate_type", sa.String(length=50), nullable=False),
        sa.Column("aggregate_id", UUID, nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("actor_type", sa.String(length=50), nullable=False),
        sa.Column("actor_id", sa.String(length=200), nullable=False),
        sa.Column("request_id", sa.String(length=100), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("safe_metadata", JSONB, nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_audit_aggregate",
        "audit_events",
        ["aggregate_type", "aggregate_id", "occurred_at"],
    )

    op.create_table(
        "idempotency_records",
        sa.Column("id", UUID, nullable=False),
        sa.Column("scope", sa.String(length=250), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("resource_type", sa.String(length=50), nullable=False),
        sa.Column("resource_id", UUID, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(request_fingerprint) = 64",
            name="ck_idempotency_fingerprint_length",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "scope",
            "idempotency_key",
            name="uq_idempotency_scope_key",
        ),
    )

    op.execute(
        """
        CREATE FUNCTION prevent_stage1_mutation() RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'immutable Stage 1 record cannot be changed';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER post_revisions_immutable
        BEFORE UPDATE OR DELETE ON post_revisions
        FOR EACH ROW EXECUTE FUNCTION prevent_stage1_mutation()
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_events_append_only
        BEFORE UPDATE OR DELETE ON audit_events
        FOR EACH ROW EXECUTE FUNCTION prevent_stage1_mutation()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER audit_events_append_only ON audit_events")
    op.execute("DROP TRIGGER post_revisions_immutable ON post_revisions")
    op.execute("DROP FUNCTION prevent_stage1_mutation()")
    op.drop_table("idempotency_records")
    op.drop_index("ix_audit_aggregate", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_table("publication_attempts")
    op.drop_index("ix_publications_stale", table_name="publications")
    op.drop_index("ix_publications_started_at", table_name="publications")
    op.drop_index("ix_publications_status", table_name="publications")
    op.drop_table("publications")
    op.drop_table("linkedin_connections")
    op.drop_index("ix_approvals_revision_id", table_name="approvals")
    op.drop_table("approvals")
    op.drop_constraint("fk_drafts_current_revision", "drafts", type_="foreignkey")
    op.drop_index("ix_post_revisions_draft_id", table_name="post_revisions")
    op.drop_table("post_revisions")
    op.drop_index("ix_drafts_current_revision_id", table_name="drafts")
    op.drop_table("drafts")
