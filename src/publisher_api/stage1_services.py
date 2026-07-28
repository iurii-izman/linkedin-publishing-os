from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from publisher_api.settings import STAGE0_REQUIRED_SCOPES, Settings
from publisher_api.stage1_database import SessionFactory, transactional_session
from publisher_api.stage1_domain import (
    CANONICALIZATION_VERSION,
    AttemptOutcome,
    DomainError,
    PublicationStatus,
    approval_fingerprint,
    stable_fingerprint,
    transition_publication,
    utc_text_sha256,
)
from publisher_api.stage1_encryption import TokenCipher
from publisher_api.stage1_logging import safe_log
from publisher_api.stage1_models import (
    Approval,
    AuditEvent,
    Draft,
    ExternalApprovalRequest,
    IdempotencyRecord,
    LinkedInConnection,
    PostRevision,
    Publication,
    PublicationAttempt,
    utc_now,
)
from publisher_api.stage1_publisher import (
    PublisherFailure,
    TextPostCommand,
    TextPublisher,
)
from publisher_api.token_store import EncryptedConnectionStore


def _not_found(aggregate: str) -> DomainError:
    return DomainError(
        f"{aggregate.upper()}_NOT_FOUND", f"{aggregate} was not found", status_code=404
    )


def _idempotent_resource(
    session: Session,
    *,
    scope: str,
    key: str,
    fingerprint: str,
) -> uuid.UUID | None:
    record = session.scalar(
        select(IdempotencyRecord).where(
            IdempotencyRecord.scope == scope,
            IdempotencyRecord.idempotency_key == key,
        )
    )
    if record is None:
        return None
    if record.request_fingerprint != fingerprint:
        raise DomainError(
            "IDEMPOTENCY_CONFLICT",
            "Idempotency key was already used with a different request",
            status_code=409,
        )
    return record.resource_id


def _remember_idempotency(
    session: Session,
    *,
    scope: str,
    key: str,
    fingerprint: str,
    resource_type: str,
    resource_id: uuid.UUID,
) -> None:
    session.add(
        IdempotencyRecord(
            scope=scope,
            idempotency_key=key,
            request_fingerprint=fingerprint,
            resource_type=resource_type,
            resource_id=resource_id,
        )
    )


class AuditService:
    _FORBIDDEN_METADATA_KEYS = frozenset(
        {
            "token",
            "access_token",
            "authorization",
            "authorization_header",
            "client_secret",
            "encryption_key",
            "signed_url",
            "post_text",
            "linkedin_body",
        }
    )

    @classmethod
    def _contains_forbidden_key(cls, value: Any) -> bool:
        if isinstance(value, dict):
            return any(
                str(key).lower() in cls._FORBIDDEN_METADATA_KEYS
                or cls._contains_forbidden_key(item)
                for key, item in value.items()
            )
        if isinstance(value, (list, tuple)):
            return any(cls._contains_forbidden_key(item) for item in value)
        return False

    @staticmethod
    def record(
        session: Session,
        *,
        aggregate_type: str,
        aggregate_id: uuid.UUID,
        event_type: str,
        actor_id: str,
        request_id: str,
        safe_metadata: dict[str, Any] | None = None,
        actor_type: str = "OWNER",
    ) -> None:
        metadata = safe_metadata or {}
        if AuditService._contains_forbidden_key(metadata):
            raise DomainError(
                "UNSAFE_AUDIT_METADATA",
                "Audit metadata contains a forbidden field",
                status_code=400,
            )
        session.add(
            AuditEvent(
                aggregate_type=aggregate_type,
                aggregate_id=aggregate_id,
                event_type=event_type,
                actor_type=actor_type,
                actor_id=actor_id,
                request_id=request_id,
                safe_metadata=metadata,
            )
        )


class DraftService:
    def __init__(self, sessions: SessionFactory) -> None:
        self._sessions = sessions

    def create(
        self, *, title: str | None, idempotency_key: str, actor: str, request_id: str
    ) -> tuple[Draft, bool]:
        fingerprint = stable_fingerprint({"title": title})
        with transactional_session(self._sessions) as session:
            existing_id = _idempotent_resource(
                session,
                scope="draft:create",
                key=idempotency_key,
                fingerprint=fingerprint,
            )
            if existing_id is not None:
                existing = session.get(Draft, existing_id)
                if existing is None:
                    raise _not_found("Draft")
                return existing, True
            draft = Draft(title=title)
            session.add(draft)
            session.flush()
            _remember_idempotency(
                session,
                scope="draft:create",
                key=idempotency_key,
                fingerprint=fingerprint,
                resource_type="DRAFT",
                resource_id=draft.id,
            )
            AuditService.record(
                session,
                aggregate_type="DRAFT",
                aggregate_id=draft.id,
                event_type="DRAFT_CREATED",
                actor_id=actor,
                request_id=request_id,
                safe_metadata={"title_present": title is not None},
            )
            return draft, False

    def get(self, draft_id: uuid.UUID) -> Draft:
        with transactional_session(self._sessions) as session:
            draft = session.get(Draft, draft_id)
            if draft is None:
                raise _not_found("Draft")
            return draft


class RevisionService:
    def __init__(self, sessions: SessionFactory) -> None:
        self._sessions = sessions

    def create(
        self,
        *,
        draft_id: uuid.UUID,
        text: str,
        created_by: str,
        idempotency_key: str,
        request_id: str,
    ) -> tuple[PostRevision, bool]:
        if not text.strip():
            raise DomainError("EMPTY_REVISION", "Revision text must not be blank", status_code=400)
        fingerprint = stable_fingerprint(
            {"draft_id": str(draft_id), "text": text, "created_by": created_by}
        )
        scope = f"revision:create:{draft_id}"
        with transactional_session(self._sessions) as session:
            existing_id = _idempotent_resource(
                session, scope=scope, key=idempotency_key, fingerprint=fingerprint
            )
            if existing_id is not None:
                existing = session.get(PostRevision, existing_id)
                if existing is None:
                    raise _not_found("Revision")
                return existing, True
            draft = session.scalar(select(Draft).where(Draft.id == draft_id).with_for_update())
            if draft is None:
                raise _not_found("Draft")
            if draft.archived_at is not None:
                raise DomainError("DRAFT_ARCHIVED", "Draft is archived", status_code=409)
            next_number = (
                session.scalar(
                    select(func.max(PostRevision.revision_number)).where(
                        PostRevision.draft_id == draft_id
                    )
                )
                or 0
            ) + 1
            revision = PostRevision(
                draft_id=draft_id,
                revision_number=next_number,
                text=text,
                text_sha256=utc_text_sha256(text),
                canonicalization_version=CANONICALIZATION_VERSION,
                supersedes_revision_id=draft.current_revision_id,
                created_by=created_by,
            )
            session.add(revision)
            session.flush()
            draft.current_revision_id = revision.id
            draft.updated_at = utc_now()
            pending_requests = list(
                session.scalars(
                    select(ExternalApprovalRequest)
                    .where(
                        ExternalApprovalRequest.draft_id == draft.id,
                        ExternalApprovalRequest.revision_id != revision.id,
                        ExternalApprovalRequest.status == "PENDING",
                    )
                    .with_for_update()
                )
            )
            for pending in pending_requests:
                pending.status = "INVALIDATED"
                pending.invalidated_at = utc_now()
                pending.invalidation_reason = "current revision changed"
                pending.updated_at = utc_now()
                AuditService.record(
                    session,
                    aggregate_type="DRAFT",
                    aggregate_id=draft.id,
                    event_type="EXTERNAL_APPROVAL_INVALIDATED",
                    actor_id=created_by,
                    request_id=request_id,
                    safe_metadata={
                        "approval_request_id": str(pending.id),
                        "revision_id": str(pending.revision_id),
                        "reason": "current revision changed",
                    },
                )
            _remember_idempotency(
                session,
                scope=scope,
                key=idempotency_key,
                fingerprint=fingerprint,
                resource_type="REVISION",
                resource_id=revision.id,
            )
            AuditService.record(
                session,
                aggregate_type="DRAFT",
                aggregate_id=draft_id,
                event_type="REVISION_CREATED",
                actor_id=created_by,
                request_id=request_id,
                safe_metadata={
                    "revision_id": str(revision.id),
                    "revision_number": next_number,
                    "text_sha256": revision.text_sha256,
                    "text_length": len(text),
                },
            )
            return revision, False

    def get(self, revision_id: uuid.UUID) -> PostRevision:
        with transactional_session(self._sessions) as session:
            revision = session.get(PostRevision, revision_id)
            if revision is None:
                raise _not_found("Revision")
            return revision

    def list_for_draft(self, draft_id: uuid.UUID) -> list[PostRevision]:
        with transactional_session(self._sessions) as session:
            if session.get(Draft, draft_id) is None:
                raise _not_found("Draft")
            return list(
                session.scalars(
                    select(PostRevision)
                    .where(PostRevision.draft_id == draft_id)
                    .order_by(PostRevision.revision_number)
                )
            )


class ApprovalService:
    def __init__(self, sessions: SessionFactory) -> None:
        self._sessions = sessions

    def approve(
        self,
        *,
        revision_id: uuid.UUID,
        approved_by: str,
        idempotency_key: str,
        request_id: str,
    ) -> tuple[Approval, bool]:
        with transactional_session(self._sessions) as session:
            return self.approve_in_session(
                session,
                revision_id=revision_id,
                approved_by=approved_by,
                idempotency_key=idempotency_key,
                request_id=request_id,
            )

    def approve_in_session(
        self,
        session: Session,
        *,
        revision_id: uuid.UUID,
        approved_by: str,
        idempotency_key: str,
        request_id: str,
    ) -> tuple[Approval, bool]:
        request_fingerprint = stable_fingerprint(
            {"revision_id": str(revision_id), "approved_by": approved_by}
        )
        existing_id = _idempotent_resource(
            session,
            scope="approval:create",
            key=idempotency_key,
            fingerprint=request_fingerprint,
        )
        if existing_id is not None:
            existing = session.get(Approval, existing_id)
            if existing is None:
                raise _not_found("Approval")
            return existing, True
        revision = session.get(PostRevision, revision_id)
        if revision is None:
            raise _not_found("Revision")
        draft = session.scalar(select(Draft).where(Draft.id == revision.draft_id).with_for_update())
        if draft is None:
            raise _not_found("Draft")
        if draft.current_revision_id != revision.id:
            raise DomainError(
                "STALE_REVISION",
                "Only the current revision can be approved",
                status_code=409,
            )
        exact_fingerprint = approval_fingerprint(str(revision.id), revision.text_sha256)
        approval = session.scalar(
            select(Approval).where(
                Approval.approval_fingerprint == exact_fingerprint,
                Approval.revoked_at.is_(None),
            )
        )
        replayed = approval is not None
        if approval is None:
            approval = Approval(
                revision_id=revision.id,
                revision_sha256=revision.text_sha256,
                approval_fingerprint=exact_fingerprint,
                approved_by=approved_by,
                idempotency_key=idempotency_key,
            )
            session.add(approval)
            session.flush()
        _remember_idempotency(
            session,
            scope="approval:create",
            key=idempotency_key,
            fingerprint=request_fingerprint,
            resource_type="APPROVAL",
            resource_id=approval.id,
        )
        if not replayed:
            AuditService.record(
                session,
                aggregate_type="DRAFT",
                aggregate_id=draft.id,
                event_type="APPROVAL_GRANTED",
                actor_id=approved_by,
                request_id=request_id,
                safe_metadata={
                    "approval_id": str(approval.id),
                    "revision_id": str(revision.id),
                    "revision_sha256": revision.text_sha256,
                    "approval_fingerprint": exact_fingerprint,
                },
            )
        return approval, replayed

    def revoke(
        self,
        *,
        approval_id: uuid.UUID,
        reason: str,
        actor: str,
        request_id: str,
    ) -> Approval:
        with transactional_session(self._sessions) as session:
            approval = session.scalar(
                select(Approval).where(Approval.id == approval_id).with_for_update()
            )
            if approval is None:
                raise _not_found("Approval")
            if approval.revoked_at is not None:
                return approval
            approval.revoked_at = utc_now()
            approval.revocation_reason = reason
            revision = session.get(PostRevision, approval.revision_id)
            if revision is None:
                raise _not_found("Revision")
            AuditService.record(
                session,
                aggregate_type="DRAFT",
                aggregate_id=revision.draft_id,
                event_type="APPROVAL_REVOKED",
                actor_id=actor,
                request_id=request_id,
                safe_metadata={"approval_id": str(approval.id), "reason": reason[:200]},
            )
            return approval


class ConnectionService:
    def __init__(self, sessions: SessionFactory, settings: Settings, cipher: TokenCipher) -> None:
        self._sessions = sessions
        self._settings = settings
        self._cipher = cipher

    def import_stage0(
        self, *, confirm: bool, request_id: str = "stage1-cli-import"
    ) -> dict[str, Any]:
        store = EncryptedConnectionStore(
            self._settings.stage0_token_store_path,
            self._settings.token_encryption_key,
        )
        stored = store.load()
        if stored.expires_at <= datetime.now(UTC):
            raise DomainError(
                "STAGE0_CONNECTION_EXPIRED",
                "Stage 0 connection is expired",
                status_code=409,
            )
        if not STAGE0_REQUIRED_SCOPES.issubset(set(stored.granted_scopes)):
            raise DomainError(
                "STAGE0_CONNECTION_SCOPES",
                "Stage 0 connection lacks required scopes",
                status_code=409,
            )
        safe_result: dict[str, Any] = {
            "dry_run": not confirm,
            "owner_subject_present": True,
            "person_urn_present": True,
            "expires_at": stored.expires_at.isoformat(),
            "scopes": sorted(stored.granted_scopes),
            "stage0_store_retained": True,
        }
        if not confirm:
            return safe_result
        with transactional_session(self._sessions) as session:
            connection = session.scalar(
                select(LinkedInConnection)
                .where(LinkedInConnection.owner_subject == stored.member_subject)
                .with_for_update()
            )
            created = connection is None
            if connection is None:
                connection = LinkedInConnection(
                    id=uuid.uuid4(),
                    owner_subject=stored.member_subject,
                    encrypted_access_token="pending",
                    token_expires_at=stored.expires_at,
                    scopes=stored.granted_scopes,
                    person_urn=stored.author_urn,
                    token_metadata={},
                )
                session.add(connection)
            ciphertext = self._cipher.encrypt(
                stored.access_token,
                connection_id=str(connection.id),
                owner_subject=stored.member_subject,
            )
            connection.encrypted_access_token = ciphertext
            connection.token_expires_at = stored.expires_at
            connection.scopes = stored.granted_scopes
            connection.person_urn = stored.author_urn
            connection.token_metadata = {
                "api_version": stored.api_version,
                "cipher_version": "v1",
                "key_id": self._cipher.key_id,
                "source": "stage0-owner-import",
            }
            connection.updated_at = utc_now()
            connection.last_validated_at = utc_now()
            connection.disabled_at = None
            session.flush()
            AuditService.record(
                session,
                aggregate_type="LINKEDIN_CONNECTION",
                aggregate_id=connection.id,
                event_type="CONNECTION_IMPORTED",
                actor_id="stage1-cli",
                request_id=request_id,
                safe_metadata={
                    "created": created,
                    "scope_count": len(connection.scopes),
                    "token_expiry": connection.token_expires_at.isoformat(),
                },
                actor_type="SYSTEM",
            )
            safe_result.update({"created": created, "connection_id": str(connection.id)})
        return safe_result


@dataclass(frozen=True, repr=False)
class ExecutionPlan:
    publication_id: uuid.UUID
    connection_id: uuid.UUID
    owner_subject: str
    encrypted_access_token: str
    person_urn: str
    text: str


class PublicationService:
    def __init__(
        self,
        sessions: SessionFactory,
        publisher: TextPublisher,
        cipher: TokenCipher,
    ) -> None:
        self._sessions = sessions
        self._publisher = publisher
        self._cipher = cipher

    @staticmethod
    def _validate_exact_approval(draft: Draft, revision: PostRevision, approval: Approval) -> None:
        if draft.current_revision_id != revision.id:
            raise DomainError(
                "STALE_REVISION",
                "Only the current revision can be published",
                status_code=409,
            )
        expected = approval_fingerprint(str(revision.id), revision.text_sha256)
        if (
            approval.revision_id != revision.id
            or approval.revision_sha256 != revision.text_sha256
            or approval.approval_fingerprint != expected
        ):
            raise DomainError(
                "APPROVAL_FINGERPRINT_MISMATCH",
                "Approval does not match the exact revision",
                status_code=409,
            )
        if approval.revoked_at is not None:
            raise DomainError(
                "APPROVAL_REVOKED",
                "Approval has been revoked",
                status_code=409,
            )

    def prepare(
        self,
        *,
        revision_id: uuid.UUID,
        approval_id: uuid.UUID,
        connection_id: uuid.UUID,
        idempotency_key: str,
        actor: str,
        request_id: str,
    ) -> tuple[Publication, bool]:
        payload = {
            "revision_id": str(revision_id),
            "approval_id": str(approval_id),
            "connection_id": str(connection_id),
        }
        idempotency_fingerprint = stable_fingerprint(payload)
        with transactional_session(self._sessions) as session:
            existing_id = _idempotent_resource(
                session,
                scope="publication:prepare",
                key=idempotency_key,
                fingerprint=idempotency_fingerprint,
            )
            if existing_id is not None:
                existing = session.get(Publication, existing_id)
                if existing is None:
                    raise _not_found("Publication")
                return existing, True
            revision = session.get(PostRevision, revision_id)
            approval = session.get(Approval, approval_id)
            connection = session.get(LinkedInConnection, connection_id)
            if revision is None:
                raise _not_found("Revision")
            if approval is None:
                raise _not_found("Approval")
            if connection is None:
                raise _not_found("LinkedIn connection")
            draft = session.scalar(
                select(Draft).where(Draft.id == revision.draft_id).with_for_update()
            )
            if draft is None:
                raise _not_found("Draft")
            self._validate_exact_approval(draft, revision, approval)
            if connection.disabled_at is not None or connection.token_expires_at <= utc_now():
                raise DomainError(
                    "CONNECTION_UNAVAILABLE",
                    "LinkedIn connection is disabled or expired",
                    status_code=409,
                )
            request_fingerprint = stable_fingerprint(
                {
                    **payload,
                    "approval_fingerprint": approval.approval_fingerprint,
                    "revision_sha256": revision.text_sha256,
                    "visibility": "PUBLIC",
                }
            )
            existing_destination = session.scalar(
                select(Publication).where(
                    Publication.revision_id == revision.id,
                    Publication.connection_id == connection.id,
                )
            )
            if existing_destination is not None:
                raise DomainError(
                    "PUBLICATION_ALREADY_EXISTS",
                    "A publication already exists for this revision and destination",
                    status_code=409,
                    publication_status=PublicationStatus(existing_destination.status),
                )
            publication = Publication(
                draft_id=draft.id,
                revision_id=revision.id,
                approval_id=approval.id,
                connection_id=connection.id,
                status=PublicationStatus.PREPARED.value,
                request_fingerprint=request_fingerprint,
                idempotency_key=idempotency_key,
            )
            session.add(publication)
            session.flush()
            _remember_idempotency(
                session,
                scope="publication:prepare",
                key=idempotency_key,
                fingerprint=idempotency_fingerprint,
                resource_type="PUBLICATION",
                resource_id=publication.id,
            )
            AuditService.record(
                session,
                aggregate_type="DRAFT",
                aggregate_id=draft.id,
                event_type="PUBLICATION_PREPARED",
                actor_id=actor,
                request_id=request_id,
                safe_metadata={
                    "publication_id": str(publication.id),
                    "revision_id": str(revision.id),
                    "request_fingerprint": request_fingerprint,
                },
            )
            return publication, False

    def _start_execution(
        self,
        *,
        publication_id: uuid.UUID,
        idempotency_key: str,
        confirmed: bool,
        actor: str,
        request_id: str,
    ) -> tuple[ExecutionPlan | None, Publication]:
        if not confirmed:
            raise DomainError(
                "EXECUTION_CONFIRMATION_REQUIRED",
                "Explicit publication execution confirmation is required",
                status_code=400,
            )
        fingerprint = stable_fingerprint({"publication_id": str(publication_id), "confirmed": True})
        with transactional_session(self._sessions) as session:
            publication = session.scalar(
                select(Publication).where(Publication.id == publication_id).with_for_update()
            )
            if publication is None:
                raise _not_found("Publication")
            existing_id = _idempotent_resource(
                session,
                scope=f"publication:execute:{publication_id}",
                key=idempotency_key,
                fingerprint=fingerprint,
            )
            if existing_id is not None:
                return None, publication
            current_status = PublicationStatus(publication.status)
            if current_status != PublicationStatus.PREPARED:
                _remember_idempotency(
                    session,
                    scope=f"publication:execute:{publication_id}",
                    key=idempotency_key,
                    fingerprint=fingerprint,
                    resource_type="PUBLICATION",
                    resource_id=publication.id,
                )
                return None, publication
            if not self._publisher.available:
                raise DomainError(
                    "LINKEDIN_PUBLISHING_DISABLED",
                    "LinkedIn publication execution is disabled by configuration",
                    status_code=409,
                )
            revision = session.get(PostRevision, publication.revision_id)
            approval = session.get(Approval, publication.approval_id)
            draft = session.get(Draft, publication.draft_id)
            connection = session.get(LinkedInConnection, publication.connection_id)
            if revision is None:
                raise _not_found("Revision")
            if approval is None:
                raise _not_found("Approval")
            if draft is None:
                raise _not_found("Draft")
            if connection is None:
                raise _not_found("LinkedIn connection")
            self._validate_exact_approval(draft, revision, approval)
            if connection.disabled_at is not None or connection.token_expires_at <= utc_now():
                raise DomainError(
                    "CONNECTION_UNAVAILABLE",
                    "LinkedIn connection is disabled or expired",
                    status_code=409,
                )
            publication.status = transition_publication(
                current_status, PublicationStatus.PUBLISHING
            ).value
            publication.started_at = utc_now()
            publication.updated_at = utc_now()
            attempt = PublicationAttempt(
                publication_id=publication.id,
                attempt_number=1,
                stage="FINAL_POST",
                outcome=AttemptOutcome.STARTED.value,
            )
            session.add(attempt)
            _remember_idempotency(
                session,
                scope=f"publication:execute:{publication_id}",
                key=idempotency_key,
                fingerprint=fingerprint,
                resource_type="PUBLICATION",
                resource_id=publication.id,
            )
            AuditService.record(
                session,
                aggregate_type="DRAFT",
                aggregate_id=draft.id,
                event_type="PUBLICATION_STARTED",
                actor_id=actor,
                request_id=request_id,
                safe_metadata={
                    "publication_id": str(publication.id),
                    "attempt_number": 1,
                },
            )
            plan = ExecutionPlan(
                publication_id=publication.id,
                connection_id=connection.id,
                owner_subject=connection.owner_subject,
                encrypted_access_token=connection.encrypted_access_token,
                person_urn=connection.person_urn,
                text=revision.text,
            )
            return plan, publication

    async def execute(
        self,
        *,
        publication_id: uuid.UUID,
        idempotency_key: str,
        confirmed: bool,
        actor: str,
        request_id: str,
    ) -> tuple[Publication, bool]:
        plan, publication = self._start_execution(
            publication_id=publication_id,
            idempotency_key=idempotency_key,
            confirmed=confirmed,
            actor=actor,
            request_id=request_id,
        )
        if plan is None:
            return publication, True
        safe_log(
            "publication_transition",
            request_id=request_id,
            aggregate_id=str(publication.draft_id),
            publication_id=str(publication.id),
            state_transition="PREPARED->PUBLISHING",
        )
        try:
            token = self._cipher.decrypt(
                plan.encrypted_access_token,
                connection_id=str(plan.connection_id),
                owner_subject=plan.owner_subject,
            )
        except ValueError:
            return (
                self._complete_failure(
                    publication_id=plan.publication_id,
                    target=PublicationStatus.FAILED,
                    failure=PublisherFailure(
                        category="CONFIGURATION",
                        code="TOKEN_DECRYPTION_FAILED",
                        message="The encrypted LinkedIn connection is not usable",
                        http_status=None,
                        request_attempted=False,
                        response_received=False,
                        certain_failure=True,
                    ),
                    actor=actor,
                    request_id=request_id,
                ),
                False,
            )
        try:
            receipt = await self._publisher.create_text_post(
                TextPostCommand(
                    access_token=token,
                    author_urn=plan.person_urn,
                    text=plan.text,
                )
            )
        except asyncio.CancelledError:
            self._complete_failure(
                publication_id=plan.publication_id,
                target=PublicationStatus.PUBLISH_UNCERTAIN,
                failure=PublisherFailure(
                    category="CANCELLATION",
                    code="FINAL_REQUEST_CANCELLED",
                    message="Final LinkedIn request was cancelled after execution started",
                    http_status=None,
                    request_attempted=True,
                    response_received=False,
                    certain_failure=False,
                ),
                actor=actor,
                request_id=request_id,
            )
            raise
        except PublisherFailure as exc:
            target = (
                PublicationStatus.FAILED
                if exc.certain_failure
                else PublicationStatus.PUBLISH_UNCERTAIN
            )
            return (
                self._complete_failure(
                    publication_id=plan.publication_id,
                    target=target,
                    failure=exc,
                    actor=actor,
                    request_id=request_id,
                ),
                False,
            )
        except Exception:
            return (
                self._complete_failure(
                    publication_id=plan.publication_id,
                    target=PublicationStatus.PUBLISH_UNCERTAIN,
                    failure=PublisherFailure(
                        category="UNEXPECTED",
                        code="FINAL_REQUEST_OUTCOME_UNKNOWN",
                        message="Final LinkedIn post outcome is uncertain",
                        http_status=None,
                        request_attempted=True,
                        response_received=False,
                        certain_failure=False,
                    ),
                    actor=actor,
                    request_id=request_id,
                ),
                False,
            )
        if receipt.http_status != 201 or not receipt.identifier.strip():
            return (
                self._complete_failure(
                    publication_id=plan.publication_id,
                    target=PublicationStatus.PUBLISH_UNCERTAIN,
                    failure=PublisherFailure(
                        category="PROTOCOL",
                        code="PUBLISH_CONFIRMATION_INVALID",
                        message="LinkedIn did not return an unambiguous publication confirmation",
                        http_status=receipt.http_status,
                        request_attempted=True,
                        response_received=True,
                        certain_failure=False,
                    ),
                    actor=actor,
                    request_id=request_id,
                ),
                False,
            )
        return (
            self._complete_success(
                publication_id=plan.publication_id,
                identifier=receipt.identifier,
                http_status=receipt.http_status,
                actor=actor,
                request_id=request_id,
            ),
            False,
        )

    def _complete_success(
        self,
        *,
        publication_id: uuid.UUID,
        identifier: str,
        http_status: int,
        actor: str,
        request_id: str,
    ) -> Publication:
        with transactional_session(self._sessions) as session:
            publication = session.scalar(
                select(Publication).where(Publication.id == publication_id).with_for_update()
            )
            if publication is None:
                raise _not_found("Publication")
            publication.status = transition_publication(
                PublicationStatus(publication.status), PublicationStatus.PUBLISHED
            ).value
            publication.linkedin_post_identifier = identifier
            publication.completed_at = utc_now()
            publication.updated_at = utc_now()
            publication.request_attempted = True
            publication.response_received = True
            attempt = session.scalar(
                select(PublicationAttempt).where(
                    PublicationAttempt.publication_id == publication.id
                )
            )
            if attempt is None:
                raise _not_found("Publication attempt")
            attempt.completed_at = utc_now()
            attempt.request_attempted = True
            attempt.response_received = True
            attempt.http_status = http_status
            attempt.outcome = AttemptOutcome.PUBLISHED.value
            attempt.linkedin_post_identifier = identifier
            AuditService.record(
                session,
                aggregate_type="DRAFT",
                aggregate_id=publication.draft_id,
                event_type="PUBLICATION_SUCCEEDED",
                actor_id=actor,
                request_id=request_id,
                safe_metadata={
                    "publication_id": str(publication.id),
                    "http_status": http_status,
                    "post_identifier_present": True,
                },
            )
            safe_log(
                "publication_transition",
                request_id=request_id,
                aggregate_id=str(publication.draft_id),
                publication_id=str(publication.id),
                state_transition="PUBLISHING->PUBLISHED",
                http_status=http_status,
                post_identifier_present=True,
            )
            return publication

    def _complete_failure(
        self,
        *,
        publication_id: uuid.UUID,
        target: PublicationStatus,
        failure: PublisherFailure,
        actor: str,
        request_id: str,
    ) -> Publication:
        with transactional_session(self._sessions) as session:
            publication = session.scalar(
                select(Publication).where(Publication.id == publication_id).with_for_update()
            )
            if publication is None:
                raise _not_found("Publication")
            publication.status = transition_publication(
                PublicationStatus(publication.status), target
            ).value
            publication.completed_at = utc_now()
            publication.updated_at = utc_now()
            publication.failure_category = failure.category
            publication.safe_error_code = failure.code
            publication.safe_error_message = failure.safe_message[:300]
            publication.request_attempted = failure.request_attempted
            publication.response_received = failure.response_received
            attempt = session.scalar(
                select(PublicationAttempt).where(
                    PublicationAttempt.publication_id == publication.id
                )
            )
            if attempt is None:
                raise _not_found("Publication attempt")
            attempt.completed_at = utc_now()
            attempt.request_attempted = failure.request_attempted
            attempt.response_received = failure.response_received
            attempt.http_status = failure.http_status
            attempt.outcome = target.value
            attempt.safe_error_category = failure.category
            attempt.safe_error_code = failure.code
            attempt.safe_error_message = failure.safe_message[:300]
            event = (
                "PUBLICATION_FAILED"
                if target == PublicationStatus.FAILED
                else "PUBLICATION_UNCERTAIN"
            )
            AuditService.record(
                session,
                aggregate_type="DRAFT",
                aggregate_id=publication.draft_id,
                event_type=event,
                actor_id=actor,
                request_id=request_id,
                safe_metadata={
                    "publication_id": str(publication.id),
                    "safe_error_category": failure.category,
                    "safe_error_code": failure.code,
                    "http_status": failure.http_status,
                },
            )
            safe_log(
                "publication_transition",
                request_id=request_id,
                aggregate_id=str(publication.draft_id),
                publication_id=str(publication.id),
                state_transition=f"PUBLISHING->{target.value}",
                safe_error_category=failure.category,
                safe_error_code=failure.code,
                http_status=failure.http_status,
            )
            return publication

    def get(self, publication_id: uuid.UUID) -> Publication:
        with transactional_session(self._sessions) as session:
            publication = session.get(Publication, publication_id)
            if publication is None:
                raise _not_found("Publication")
            return publication

    def reconcile_stale(
        self,
        *,
        threshold_seconds: int,
        confirm: bool,
        request_id: str = "stage1-cli-reconcile",
    ) -> list[uuid.UUID]:
        cutoff = utc_now() - timedelta(seconds=threshold_seconds)
        with transactional_session(self._sessions) as session:
            stale = list(
                session.scalars(
                    select(Publication)
                    .where(
                        Publication.status == PublicationStatus.PUBLISHING.value,
                        Publication.started_at < cutoff,
                    )
                    .order_by(Publication.started_at)
                    .with_for_update(skip_locked=True)
                )
            )
            identifiers = [item.id for item in stale]
            if not confirm:
                return identifiers
            for publication in stale:
                publication.status = transition_publication(
                    PublicationStatus.PUBLISHING,
                    PublicationStatus.PUBLISH_UNCERTAIN,
                ).value
                publication.completed_at = utc_now()
                publication.failure_category = "PROCESS_RECOVERY"
                publication.safe_error_code = "STALE_PUBLISHING_RECONCILED"
                publication.safe_error_message = (
                    "Publication was left in PUBLISHING and requires manual verification"
                )
                attempt = session.scalar(
                    select(PublicationAttempt).where(
                        PublicationAttempt.publication_id == publication.id
                    )
                )
                if attempt is not None:
                    attempt.completed_at = utc_now()
                    attempt.outcome = AttemptOutcome.PUBLISH_UNCERTAIN.value
                    attempt.safe_error_category = "PROCESS_RECOVERY"
                    attempt.safe_error_code = "STALE_PUBLISHING_RECONCILED"
                AuditService.record(
                    session,
                    aggregate_type="DRAFT",
                    aggregate_id=publication.draft_id,
                    event_type="PUBLICATION_UNCERTAIN",
                    actor_id="stage1-cli",
                    request_id=request_id,
                    safe_metadata={
                        "publication_id": str(publication.id),
                        "safe_error_code": "STALE_PUBLISHING_RECONCILED",
                    },
                    actor_type="SYSTEM",
                )
            return identifiers


class Stage1Services:
    def __init__(
        self,
        sessions: SessionFactory,
        settings: Settings,
        publisher: TextPublisher,
    ) -> None:
        cipher = TokenCipher(settings.token_encryption_key, settings.stage1_token_key_id)
        self.drafts = DraftService(sessions)
        self.revisions = RevisionService(sessions)
        self.approvals = ApprovalService(sessions)
        self.connections = ConnectionService(sessions, settings, cipher)
        self.publications = PublicationService(sessions, publisher, cipher)
        self._sessions = sessions

    def draft_audit(self, draft_id: uuid.UUID) -> list[AuditEvent]:
        with transactional_session(self._sessions) as session:
            if session.get(Draft, draft_id) is None:
                raise _not_found("Draft")
            return list(
                session.scalars(
                    select(AuditEvent)
                    .where(
                        AuditEvent.aggregate_type == "DRAFT",
                        AuditEvent.aggregate_id == draft_id,
                    )
                    .order_by(AuditEvent.occurred_at, AuditEvent.id)
                )
            )

    def publication_attempt_count(self, publication_id: uuid.UUID) -> int:
        with transactional_session(self._sessions) as session:
            return int(
                session.scalar(
                    select(func.count(PublicationAttempt.id)).where(
                        PublicationAttempt.publication_id == publication_id
                    )
                )
                or 0
            )

    def safe_audit_export(self) -> list[dict[str, Any]]:
        with transactional_session(self._sessions) as session:
            events = list(session.scalars(select(AuditEvent).order_by(AuditEvent.occurred_at)))
            return [
                {
                    "id": str(event.id),
                    "aggregate_type": event.aggregate_type,
                    "aggregate_id": str(event.aggregate_id),
                    "event_type": event.event_type,
                    "actor_type": event.actor_type,
                    "actor_id": event.actor_id,
                    "request_id": event.request_id,
                    "occurred_at": event.occurred_at.isoformat(),
                    "safe_metadata": event.safe_metadata,
                }
                for event in events
            ]
