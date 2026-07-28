import secrets
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse

from publisher_api.settings import Settings
from publisher_api.stage1_models import Approval, AuditEvent, Draft, PostRevision, Publication
from publisher_api.stage1_schemas import (
    ApprovalCreate,
    ApprovalResponse,
    ApprovalRevoke,
    AuditEventResponse,
    DraftCreate,
    DraftResponse,
    PublicationExecute,
    PublicationPrepare,
    PublicationResponse,
    RevisionCreate,
    RevisionResponse,
)
from publisher_api.stage1_services import Stage1Services

IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=16, max_length=128)]


def _draft_response(draft: Draft) -> DraftResponse:
    return DraftResponse.model_validate(
        {
            "id": draft.id,
            "title": draft.title,
            "current_revision_id": draft.current_revision_id,
            "created_at": draft.created_at,
            "updated_at": draft.updated_at,
            "archived_at": draft.archived_at,
        }
    )


def _revision_response(revision: PostRevision) -> RevisionResponse:
    return RevisionResponse.model_validate(revision, from_attributes=True)


def _approval_response(approval: Approval) -> ApprovalResponse:
    return ApprovalResponse.model_validate(approval, from_attributes=True)


def _publication_response(publication: Publication) -> PublicationResponse:
    return PublicationResponse.model_validate(
        {
            "id": publication.id,
            "draft_id": publication.draft_id,
            "revision_id": publication.revision_id,
            "approval_id": publication.approval_id,
            "connection_id": publication.connection_id,
            "status": publication.status,
            "request_fingerprint": publication.request_fingerprint,
            "linkedin_post_identifier_present": (publication.linkedin_post_identifier is not None),
            "prepared_at": publication.prepared_at,
            "started_at": publication.started_at,
            "completed_at": publication.completed_at,
            "failure_category": publication.failure_category,
            "safe_error_code": publication.safe_error_code,
            "safe_error_message": publication.safe_error_message,
            "request_attempted": publication.request_attempted,
            "response_received": publication.response_received,
            "created_at": publication.created_at,
            "updated_at": publication.updated_at,
        }
    )


def _audit_response(event: AuditEvent) -> AuditEventResponse:
    return AuditEventResponse.model_validate(event, from_attributes=True)


def _json(model: Any, status_code: int) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=model.model_dump(mode="json"),
    )


def create_stage1_router(settings: Settings, services: Stage1Services) -> APIRouter:
    router = APIRouter(prefix="/v1")

    def owner_auth(
        owner_key: Annotated[str | None, Header(alias="X-Owner-Key")] = None,
    ) -> str:
        if owner_key is None:
            from publisher_api.stage1_domain import DomainError

            raise DomainError(
                "OWNER_AUTH_REQUIRED",
                "Owner authentication is required",
                status_code=401,
            )
        if not secrets.compare_digest(
            owner_key,
            settings.owner_key.get_secret_value(),
        ):
            from publisher_api.stage1_domain import DomainError

            raise DomainError(
                "OWNER_AUTH_FORBIDDEN",
                "Owner authentication failed",
                status_code=403,
            )
        return "owner"

    Owner = Annotated[str, Depends(owner_auth)]

    @router.post("/drafts", response_model=DraftResponse)
    def create_draft(
        body: DraftCreate,
        request: Request,
        idempotency_key: IdempotencyKey,
        owner: Owner,
    ) -> JSONResponse:
        draft, replayed = services.drafts.create(
            title=body.title,
            idempotency_key=idempotency_key,
            actor=owner,
            request_id=request.state.request_id,
        )
        return _json(_draft_response(draft), 200 if replayed else 201)

    @router.get("/drafts/{draft_id}", response_model=DraftResponse)
    def get_draft(draft_id: uuid.UUID, owner: Owner) -> DraftResponse:
        del owner
        return _draft_response(services.drafts.get(draft_id))

    @router.post("/drafts/{draft_id}/revisions", response_model=RevisionResponse)
    def create_revision(
        draft_id: uuid.UUID,
        body: RevisionCreate,
        request: Request,
        idempotency_key: IdempotencyKey,
        owner: Owner,
    ) -> JSONResponse:
        revision, replayed = services.revisions.create(
            draft_id=draft_id,
            text=body.text,
            created_by=body.created_by,
            idempotency_key=idempotency_key,
            request_id=request.state.request_id,
        )
        del owner
        return _json(_revision_response(revision), 200 if replayed else 201)

    @router.get("/drafts/{draft_id}/revisions", response_model=list[RevisionResponse])
    def list_revisions(draft_id: uuid.UUID, owner: Owner) -> list[RevisionResponse]:
        del owner
        return [_revision_response(item) for item in services.revisions.list_for_draft(draft_id)]

    @router.get("/revisions/{revision_id}", response_model=RevisionResponse)
    def get_revision(revision_id: uuid.UUID, owner: Owner) -> RevisionResponse:
        del owner
        return _revision_response(services.revisions.get(revision_id))

    @router.post("/revisions/{revision_id}/approve", response_model=ApprovalResponse)
    def approve_revision(
        revision_id: uuid.UUID,
        body: ApprovalCreate,
        request: Request,
        idempotency_key: IdempotencyKey,
        owner: Owner,
    ) -> JSONResponse:
        approval, replayed = services.approvals.approve(
            revision_id=revision_id,
            approved_by=body.approved_by,
            idempotency_key=idempotency_key,
            request_id=request.state.request_id,
        )
        del owner
        return _json(_approval_response(approval), 200 if replayed else 201)

    @router.post("/approvals/{approval_id}/revoke", response_model=ApprovalResponse)
    def revoke_approval(
        approval_id: uuid.UUID,
        body: ApprovalRevoke,
        request: Request,
        owner: Owner,
    ) -> ApprovalResponse:
        return _approval_response(
            services.approvals.revoke(
                approval_id=approval_id,
                reason=body.reason,
                actor=owner,
                request_id=request.state.request_id,
            )
        )

    @router.post("/publications/prepare", response_model=PublicationResponse)
    def prepare_publication(
        body: PublicationPrepare,
        request: Request,
        idempotency_key: IdempotencyKey,
        owner: Owner,
    ) -> JSONResponse:
        publication, replayed = services.publications.prepare(
            revision_id=body.revision_id,
            approval_id=body.approval_id,
            connection_id=body.connection_id,
            idempotency_key=idempotency_key,
            actor=owner,
            request_id=request.state.request_id,
        )
        return _json(_publication_response(publication), 200 if replayed else 201)

    @router.post("/publications/{publication_id}/execute", response_model=PublicationResponse)
    async def execute_publication(
        publication_id: uuid.UUID,
        body: PublicationExecute,
        request: Request,
        idempotency_key: IdempotencyKey,
        owner: Owner,
    ) -> JSONResponse:
        publication, replayed = await services.publications.execute(
            publication_id=publication_id,
            idempotency_key=idempotency_key,
            confirmed=body.confirm_execute,
            actor=owner,
            request_id=request.state.request_id,
        )
        return _json(_publication_response(publication), 200 if replayed else 200)

    @router.get("/publications/{publication_id}", response_model=PublicationResponse)
    def get_publication(publication_id: uuid.UUID, owner: Owner) -> PublicationResponse:
        del owner
        return _publication_response(services.publications.get(publication_id))

    @router.get("/drafts/{draft_id}/audit", response_model=list[AuditEventResponse])
    def get_draft_audit(draft_id: uuid.UUID, owner: Owner) -> list[AuditEventResponse]:
        del owner
        return [_audit_response(event) for event in services.draft_audit(draft_id)]

    return router
