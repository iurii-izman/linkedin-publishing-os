from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from publisher_api.settings import Settings
from publisher_api.stage1_database import SessionFactory, transactional_session
from publisher_api.stage1_domain import DomainError, approval_fingerprint, stable_fingerprint
from publisher_api.stage1_models import (
    Draft,
    ExternalApprovalRequest,
    PostRevision,
    Publication,
    TelegramDelivery,
    utc_now,
)
from publisher_api.stage1_services import (
    ApprovalService,
    AuditService,
    Stage1Services,
    _idempotent_resource,
    _remember_idempotency,
)


def callback_token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _not_found() -> DomainError:
    return DomainError(
        "EXTERNAL_APPROVAL_NOT_FOUND",
        "External approval request was not found",
        status_code=404,
    )


@dataclass(frozen=True)
class DecisionResult:
    request: ExternalApprovalRequest
    replayed: bool


class ExternalApprovalRequestService:
    def __init__(
        self,
        sessions: SessionFactory,
        settings: Settings,
        approvals: ApprovalService,
    ) -> None:
        self._sessions = sessions
        self._settings = settings
        self._approvals = approvals

    def _require_telegram_configuration(self) -> tuple[int, int]:
        user_id = self._settings.telegram_owner_user_id
        chat_id = self._settings.telegram_owner_chat_id
        if user_id is None or chat_id is None:
            raise DomainError(
                "TELEGRAM_OWNER_NOT_CONFIGURED",
                "Telegram owner identity is not configured",
                status_code=409,
            )
        return user_id, chat_id

    @staticmethod
    def _expire_if_needed(
        session: Session,
        item: ExternalApprovalRequest,
        *,
        request_id: str,
    ) -> None:
        if item.status == "PENDING" and item.expires_at <= datetime.now(UTC):
            item.status = "EXPIRED"
            item.updated_at = utc_now()
            AuditService.record(
                session,
                aggregate_type="DRAFT",
                aggregate_id=item.draft_id,
                event_type="EXTERNAL_APPROVAL_EXPIRED",
                actor_id="system",
                actor_type="SYSTEM",
                request_id=request_id,
                safe_metadata={
                    "approval_request_id": str(item.id),
                    "revision_id": str(item.revision_id),
                },
            )

    def create(
        self,
        *,
        revision_id: uuid.UUID,
        requested_by: str,
        idempotency_key: str,
        request_id: str,
    ) -> tuple[ExternalApprovalRequest, str | None, bool]:
        owner_user_id, owner_chat_id = self._require_telegram_configuration()
        fingerprint = stable_fingerprint({"revision_id": str(revision_id), "channel": "TELEGRAM"})
        with transactional_session(self._sessions) as session:
            existing_id = _idempotent_resource(
                session,
                scope="external-approval:create",
                key=idempotency_key,
                fingerprint=fingerprint,
            )
            if existing_id is not None:
                existing = session.get(ExternalApprovalRequest, existing_id)
                if existing is None:
                    raise _not_found()
                return existing, None, True
            revision = session.get(PostRevision, revision_id)
            if revision is None:
                raise DomainError("REVISION_NOT_FOUND", "Revision was not found", status_code=404)
            draft = session.scalar(
                select(Draft).where(Draft.id == revision.draft_id).with_for_update()
            )
            if draft is None:
                raise DomainError("DRAFT_NOT_FOUND", "Draft was not found", status_code=404)
            if draft.current_revision_id != revision.id:
                raise DomainError(
                    "STALE_REVISION",
                    "Only the current revision can request approval",
                    status_code=409,
                )
            pending = session.scalar(
                select(ExternalApprovalRequest).where(
                    ExternalApprovalRequest.revision_id == revision.id,
                    ExternalApprovalRequest.channel == "TELEGRAM",
                    ExternalApprovalRequest.status == "PENDING",
                )
            )
            if pending is not None:
                self._expire_if_needed(session, pending, request_id=request_id)
                if pending.status == "PENDING":
                    raise DomainError(
                        "APPROVAL_REQUEST_ALREADY_PENDING",
                        "A pending approval request already exists for this revision",
                        status_code=409,
                    )
            plain_token = secrets.token_urlsafe(32)
            item = ExternalApprovalRequest(
                draft_id=draft.id,
                revision_id=revision.id,
                revision_sha256=revision.text_sha256,
                approval_fingerprint=approval_fingerprint(str(revision.id), revision.text_sha256),
                channel="TELEGRAM",
                status="PENDING",
                callback_token_hash=callback_token_hash(plain_token),
                telegram_owner_user_id=owner_user_id,
                telegram_chat_id=owner_chat_id,
                requested_by=requested_by,
                expires_at=utc_now()
                + timedelta(seconds=self._settings.approval_request_ttl_seconds),
                idempotency_key=idempotency_key,
            )
            session.add(item)
            session.flush()
            _remember_idempotency(
                session,
                scope="external-approval:create",
                key=idempotency_key,
                fingerprint=fingerprint,
                resource_type="EXTERNAL_APPROVAL_REQUEST",
                resource_id=item.id,
            )
            AuditService.record(
                session,
                aggregate_type="DRAFT",
                aggregate_id=draft.id,
                event_type="EXTERNAL_APPROVAL_REQUESTED",
                actor_id=requested_by,
                request_id=request_id,
                safe_metadata={
                    "approval_request_id": str(item.id),
                    "revision_id": str(revision.id),
                    "text_length": len(revision.text),
                    "revision_sha256_prefix": revision.text_sha256[:12],
                },
            )
            return item, plain_token, False

    def get(self, request_id_value: uuid.UUID, *, request_id: str) -> ExternalApprovalRequest:
        with transactional_session(self._sessions) as session:
            item = session.scalar(
                select(ExternalApprovalRequest)
                .where(ExternalApprovalRequest.id == request_id_value)
                .with_for_update()
            )
            if item is None:
                raise _not_found()
            self._expire_if_needed(session, item, request_id=request_id)
            return item

    def preview(self, request_id_value: uuid.UUID, *, request_id: str) -> dict[str, object]:
        with transactional_session(self._sessions) as session:
            item = session.scalar(
                select(ExternalApprovalRequest)
                .where(ExternalApprovalRequest.id == request_id_value)
                .with_for_update()
            )
            if item is None:
                raise _not_found()
            self._expire_if_needed(session, item, request_id=request_id)
            if item.status not in {"PENDING", "APPROVED", "CONSUMED"}:
                raise DomainError(
                    "APPROVAL_REQUEST_NOT_PREVIEWABLE",
                    "Approval request is not active",
                    status_code=409,
                )
            revision = session.get(PostRevision, item.revision_id)
            draft = session.get(Draft, item.draft_id)
            if revision is None or draft is None:
                raise _not_found()
            return {
                "request_id": item.id,
                "draft_title": draft.title,
                "revision_number": revision.revision_number,
                "exact_text": revision.text,
                "text_length": len(revision.text),
                "revision_sha256_prefix": revision.text_sha256[:12],
                "expires_at": item.expires_at,
                "actions": ["APPROVE_AND_PUBLISH", "REJECT"],
                "warning": "Publication starts immediately after approval.",
            }

    def invalidate(
        self,
        request_id_value: uuid.UUID,
        *,
        reason: str,
        actor: str,
        request_id: str,
    ) -> ExternalApprovalRequest:
        with transactional_session(self._sessions) as session:
            item = session.scalar(
                select(ExternalApprovalRequest)
                .where(ExternalApprovalRequest.id == request_id_value)
                .with_for_update()
            )
            if item is None:
                raise _not_found()
            self._expire_if_needed(session, item, request_id=request_id)
            if item.status == "INVALIDATED":
                return item
            if item.status != "PENDING":
                raise DomainError(
                    "APPROVAL_REQUEST_TERMINAL",
                    "Only a pending approval request can be invalidated",
                    status_code=409,
                )
            item.status = "INVALIDATED"
            item.invalidated_at = utc_now()
            item.invalidation_reason = reason
            item.updated_at = utc_now()
            AuditService.record(
                session,
                aggregate_type="DRAFT",
                aggregate_id=item.draft_id,
                event_type="EXTERNAL_APPROVAL_INVALIDATED",
                actor_id=actor,
                request_id=request_id,
                safe_metadata={
                    "approval_request_id": str(item.id),
                    "revision_id": str(item.revision_id),
                    "reason": reason[:200],
                },
            )
            return item

    def decide(
        self,
        *,
        callback_token: str,
        telegram_user_id: int,
        telegram_chat_id: int,
        decision: str,
        idempotency_key: str,
        callback_query_present: bool,
        message_external_id: str | None,
        request_id: str,
    ) -> DecisionResult:
        digest = callback_token_hash(callback_token)
        owner_user_id, owner_chat_id = self._require_telegram_configuration()
        expired = False
        with transactional_session(self._sessions) as session:
            item = session.scalar(
                select(ExternalApprovalRequest)
                .where(ExternalApprovalRequest.callback_token_hash == digest)
                .with_for_update()
            )
            if item is None or not secrets.compare_digest(item.callback_token_hash, digest):
                raise _not_found()
            self._expire_if_needed(session, item, request_id=request_id)
            expired = item.status == "EXPIRED"
        if expired:
            raise DomainError(
                "APPROVAL_REQUEST_TERMINAL",
                "Approval request is no longer actionable",
                status_code=409,
            )
        with transactional_session(self._sessions) as session:
            item = session.scalar(
                select(ExternalApprovalRequest)
                .where(ExternalApprovalRequest.callback_token_hash == digest)
                .with_for_update()
            )
            if item is None or not secrets.compare_digest(item.callback_token_hash, digest):
                raise _not_found()
            key_owner = session.scalar(
                select(ExternalApprovalRequest).where(
                    ExternalApprovalRequest.decision_idempotency_key == idempotency_key
                )
            )
            if key_owner is not None and key_owner.id != item.id:
                raise DomainError(
                    "IDEMPOTENCY_CONFLICT",
                    "Decision idempotency key was already used",
                    status_code=409,
                )
            if telegram_user_id != owner_user_id or telegram_user_id != item.telegram_owner_user_id:
                raise DomainError(
                    "TELEGRAM_OWNER_FORBIDDEN",
                    "Telegram owner identity did not match",
                    status_code=403,
                )
            if telegram_chat_id != owner_chat_id or telegram_chat_id != item.telegram_chat_id:
                raise DomainError(
                    "TELEGRAM_CHAT_FORBIDDEN",
                    "Telegram chat identity did not match",
                    status_code=403,
                )
            if item.status in {"APPROVED", "REJECTED", "CONSUMED"}:
                if item.decision != decision:
                    raise DomainError(
                        "APPROVAL_DECISION_CONFLICT",
                        "Approval request already has a different decision",
                        status_code=409,
                    )
                return DecisionResult(item, True)
            if item.status != "PENDING":
                raise DomainError(
                    "APPROVAL_REQUEST_TERMINAL",
                    "Approval request is no longer actionable",
                    status_code=409,
                )
            revision = session.get(PostRevision, item.revision_id)
            draft = session.scalar(select(Draft).where(Draft.id == item.draft_id).with_for_update())
            if revision is None or draft is None:
                raise _not_found()
            expected_fingerprint = approval_fingerprint(str(revision.id), revision.text_sha256)
            if (
                draft.current_revision_id != revision.id
                or revision.text_sha256 != item.revision_sha256
                or not secrets.compare_digest(expected_fingerprint, item.approval_fingerprint)
            ):
                item.status = "INVALIDATED"
                item.invalidated_at = utc_now()
                item.invalidation_reason = "current revision changed"
                raise DomainError(
                    "STALE_APPROVAL_REQUEST",
                    "Approval request no longer matches the current revision",
                    status_code=409,
                )
            item.decision = decision
            item.decided_at = utc_now()
            item.decision_actor_id = str(telegram_user_id)
            item.decision_idempotency_key = idempotency_key
            item.message_external_id = message_external_id
            item.updated_at = utc_now()
            if decision == "REJECT":
                item.status = "REJECTED"
                event = "EXTERNAL_APPROVAL_REJECTED"
            else:
                approval, _ = self._approvals.approve_in_session(
                    session,
                    revision_id=revision.id,
                    approved_by=f"telegram:{telegram_user_id}",
                    idempotency_key=f"external-approval:{item.id}",
                    request_id=request_id,
                )
                item.approval_id = approval.id
                item.status = "APPROVED"
                event = "EXTERNAL_APPROVAL_APPROVED"
            AuditService.record(
                session,
                aggregate_type="DRAFT",
                aggregate_id=draft.id,
                event_type=event,
                actor_id=f"telegram:{telegram_user_id}",
                request_id=request_id,
                safe_metadata={
                    "approval_request_id": str(item.id),
                    "revision_id": str(item.revision_id),
                    "decision": decision,
                    "callback_query_present": callback_query_present,
                },
            )
            return DecisionResult(item, False)


class OrchestrationService:
    def __init__(
        self,
        sessions: SessionFactory,
        stage1: Stage1Services,
    ) -> None:
        self._sessions = sessions
        self._stage1 = stage1

    def record_delivery(
        self,
        *,
        request_id_value: uuid.UUID,
        phase: str,
        delivery_status: str,
        message_external_id: str | None,
        safe_error_category: str | None,
        idempotency_key: str,
        request_id: str,
    ) -> TelegramDelivery:
        with transactional_session(self._sessions) as session:
            item = session.get(ExternalApprovalRequest, request_id_value)
            if item is None:
                raise _not_found()
            existing = session.scalar(
                select(TelegramDelivery).where(
                    TelegramDelivery.approval_request_id == item.id,
                    TelegramDelivery.phase == phase,
                )
            )
            if existing is not None:
                if (
                    existing.delivery_status != delivery_status
                    or existing.message_external_id != message_external_id
                ):
                    raise DomainError(
                        "DELIVERY_RESULT_CONFLICT",
                        "Delivery result already differs",
                        status_code=409,
                    )
                return existing
            delivery = TelegramDelivery(
                approval_request_id=item.id,
                phase=phase,
                delivery_status=delivery_status,
                message_external_id=message_external_id,
                sent_at=utc_now() if delivery_status == "SENT" else None,
                edited_at=utc_now() if phase == "RESULT" and delivery_status == "SENT" else None,
                safe_error_category=safe_error_category,
                attempts=1,
                idempotency_key=idempotency_key,
            )
            session.add(delivery)
            if message_external_id is not None:
                item.message_external_id = message_external_id
            event = (
                "TELEGRAM_DELIVERY_SUCCEEDED"
                if delivery_status == "SENT"
                else "TELEGRAM_DELIVERY_FAILED"
            )
            AuditService.record(
                session,
                aggregate_type="DRAFT",
                aggregate_id=item.draft_id,
                event_type=event,
                actor_id="n8n",
                actor_type="SERVICE",
                request_id=request_id,
                safe_metadata={
                    "approval_request_id": str(item.id),
                    "phase": phase,
                    "delivery_status": delivery_status,
                },
            )
            if phase == "RESULT":
                AuditService.record(
                    session,
                    aggregate_type="DRAFT",
                    aggregate_id=item.draft_id,
                    event_type="ORCHESTRATION_RESULT_DELIVERED",
                    actor_id="n8n",
                    actor_type="SERVICE",
                    request_id=request_id,
                    safe_metadata={
                        "approval_request_id": str(item.id),
                        "delivery_status": delivery_status,
                    },
                )
            return delivery

    def prepare(
        self,
        *,
        request_id_value: uuid.UUID,
        connection_id: uuid.UUID,
        idempotency_key: str,
        request_id: str,
    ) -> Publication:
        with transactional_session(self._sessions) as session:
            item = session.scalar(
                select(ExternalApprovalRequest)
                .where(ExternalApprovalRequest.id == request_id_value)
                .with_for_update()
            )
            if item is None:
                raise _not_found()
            if item.status == "CONSUMED" and item.publication_id is not None:
                return self._stage1.publications.get(item.publication_id)
            if item.status != "APPROVED" or item.approval_id is None:
                raise DomainError(
                    "APPROVAL_REQUEST_NOT_APPROVED",
                    "Approval request cannot prepare a publication",
                    status_code=409,
                )
            revision_id = item.revision_id
            approval_id = item.approval_id
            draft_id = item.draft_id
            AuditService.record(
                session,
                aggregate_type="DRAFT",
                aggregate_id=draft_id,
                event_type="ORCHESTRATION_PREPARE_REQUESTED",
                actor_id="n8n",
                actor_type="SERVICE",
                request_id=request_id,
                safe_metadata={"approval_request_id": str(item.id)},
            )
        publication, _ = self._stage1.publications.prepare(
            revision_id=revision_id,
            approval_id=approval_id,
            connection_id=connection_id,
            idempotency_key=idempotency_key,
            actor="n8n",
            request_id=request_id,
        )
        with transactional_session(self._sessions) as session:
            item = session.scalar(
                select(ExternalApprovalRequest)
                .where(ExternalApprovalRequest.id == request_id_value)
                .with_for_update()
            )
            if item is None:
                raise _not_found()
            item.status = "CONSUMED"
            item.consumed_at = item.consumed_at or utc_now()
            item.publication_id = publication.id
            item.updated_at = utc_now()
            AuditService.record(
                session,
                aggregate_type="DRAFT",
                aggregate_id=item.draft_id,
                event_type="EXTERNAL_APPROVAL_CONSUMED",
                actor_id="n8n",
                actor_type="SERVICE",
                request_id=request_id,
                safe_metadata={
                    "approval_request_id": str(item.id),
                    "publication_id": str(publication.id),
                },
            )
        return publication

    async def execute(
        self,
        *,
        request_id_value: uuid.UUID,
        publication_id: uuid.UUID,
        idempotency_key: str,
        confirmed: bool,
        request_id: str,
    ) -> Publication:
        with transactional_session(self._sessions) as session:
            item = session.get(ExternalApprovalRequest, request_id_value)
            if item is None:
                raise _not_found()
            if item.status != "CONSUMED" or item.publication_id != publication_id:
                raise DomainError(
                    "ORCHESTRATION_PUBLICATION_MISMATCH",
                    "Publication is not bound to this approval request",
                    status_code=409,
                )
            AuditService.record(
                session,
                aggregate_type="DRAFT",
                aggregate_id=item.draft_id,
                event_type="ORCHESTRATION_EXECUTE_REQUESTED",
                actor_id="n8n",
                actor_type="SERVICE",
                request_id=request_id,
                safe_metadata={
                    "approval_request_id": str(item.id),
                    "publication_id": str(publication_id),
                },
            )
        publication, _ = await self._stage1.publications.execute(
            publication_id=publication_id,
            idempotency_key=idempotency_key,
            confirmed=confirmed,
            actor="n8n",
            request_id=request_id,
        )
        return publication

    def get_publication(self, publication_id: uuid.UUID) -> Publication:
        return self._stage1.publications.get(publication_id)


class Stage2Services:
    def __init__(
        self,
        sessions: SessionFactory,
        settings: Settings,
        stage1: Stage1Services,
    ) -> None:
        self.approval_requests = ExternalApprovalRequestService(
            sessions, settings, stage1.approvals
        )
        self.orchestration = OrchestrationService(sessions, stage1)
