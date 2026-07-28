import secrets
import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse

from publisher_api.settings import Settings
from publisher_api.stage1_api import _publication_response
from publisher_api.stage1_domain import DomainError
from publisher_api.stage1_models import ExternalApprovalRequest
from publisher_api.stage1_schemas import PublicationResponse
from publisher_api.stage2_schemas import (
    ApprovalDecisionCreate,
    ApprovalDecisionResponse,
    ExternalApprovalInvalidate,
    ExternalApprovalRequestCreate,
    ExternalApprovalRequestResponse,
    OrchestrationExecute,
    OrchestrationPrepare,
    TelegramDeliveryResult,
    TelegramPreviewResponse,
)
from publisher_api.stage2_services import Stage2Services

IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=16, max_length=128)]


def _request_response(
    item: ExternalApprovalRequest,
    *,
    callback_token: str | None = None,
    replayed: bool = False,
    preview: dict[str, object] | None = None,
) -> ExternalApprovalRequestResponse:
    return ExternalApprovalRequestResponse.model_validate(
        {
            "id": item.id,
            "draft_id": item.draft_id,
            "revision_id": item.revision_id,
            "status": item.status,
            "channel": item.channel,
            "revision_sha256_prefix": item.revision_sha256[:12],
            "approval_fingerprint": item.approval_fingerprint,
            "expires_at": item.expires_at,
            "decision": item.decision,
            "approval_id": item.approval_id,
            "publication_id": item.publication_id,
            "callback_token": callback_token,
            "replayed": replayed,
            "preview": preview,
        }
    )


def _json(model: Any, status_code: int) -> JSONResponse:
    return JSONResponse(status_code=status_code, content=model.model_dump(mode="json"))


def create_stage2_router(settings: Settings, services: Stage2Services) -> APIRouter:
    router = APIRouter(prefix="/v1")

    def owner_auth(
        owner_key: Annotated[str | None, Header(alias="X-Owner-Key")] = None,
    ) -> str:
        if owner_key is None:
            raise DomainError(
                "OWNER_AUTH_REQUIRED", "Owner authentication is required", status_code=401
            )
        if not secrets.compare_digest(owner_key, settings.owner_key.get_secret_value()):
            raise DomainError(
                "OWNER_AUTH_FORBIDDEN", "Owner authentication failed", status_code=403
            )
        return "owner"

    def service_auth(
        service_key: Annotated[str | None, Header(alias="X-N8N-Service-Key")] = None,
    ) -> str:
        configured = settings.n8n_service_key
        if configured is None:
            raise DomainError(
                "ORCHESTRATION_DISABLED",
                "Orchestration service authentication is not configured",
                status_code=503,
            )
        if service_key is None or not secrets.compare_digest(
            service_key, configured.get_secret_value()
        ):
            raise DomainError(
                "ORCHESTRATION_FORBIDDEN",
                "Orchestration service authentication failed",
                status_code=403,
            )
        return "n8n"

    Owner = Annotated[str, Depends(owner_auth)]
    Service = Annotated[str, Depends(service_auth)]

    @router.post(
        "/revisions/{revision_id}/external-approval-requests",
        response_model=ExternalApprovalRequestResponse,
    )
    def create_external_approval(
        revision_id: uuid.UUID,
        body: ExternalApprovalRequestCreate,
        request: Request,
        idempotency_key: IdempotencyKey,
        owner: Owner,
    ) -> JSONResponse:
        item, callback_token, replayed = services.approval_requests.create(
            revision_id=revision_id,
            requested_by=body.requested_by or owner,
            idempotency_key=idempotency_key,
            request_id=request.state.request_id,
        )
        preview = services.approval_requests.preview(item.id, request_id=request.state.request_id)
        return _json(
            _request_response(
                item,
                callback_token=callback_token,
                replayed=replayed,
                preview=preview,
            ),
            200 if replayed else 201,
        )

    @router.get(
        "/external-approval-requests/{request_id_value}",
        response_model=ExternalApprovalRequestResponse,
    )
    def get_external_approval(
        request_id_value: uuid.UUID,
        request: Request,
        owner: Owner,
    ) -> ExternalApprovalRequestResponse:
        del owner
        item = services.approval_requests.get(request_id_value, request_id=request.state.request_id)
        return _request_response(item)

    @router.post(
        "/external-approval-requests/{request_id_value}/invalidate",
        response_model=ExternalApprovalRequestResponse,
    )
    def invalidate_external_approval(
        request_id_value: uuid.UUID,
        body: ExternalApprovalInvalidate,
        request: Request,
        owner: Owner,
    ) -> ExternalApprovalRequestResponse:
        item = services.approval_requests.invalidate(
            request_id_value,
            reason=body.reason,
            actor=owner,
            request_id=request.state.request_id,
        )
        return _request_response(item)

    @router.get(
        "/orchestration/approval-requests/{request_id_value}/preview",
        response_model=TelegramPreviewResponse,
    )
    def orchestration_preview(
        request_id_value: uuid.UUID,
        request: Request,
        service: Service,
    ) -> TelegramPreviewResponse:
        del service
        return TelegramPreviewResponse.model_validate(
            services.approval_requests.preview(
                request_id_value, request_id=request.state.request_id
            )
        )

    @router.post(
        "/orchestration/approval-decisions",
        response_model=ApprovalDecisionResponse,
    )
    def orchestration_decision(
        body: ApprovalDecisionCreate,
        request: Request,
        idempotency_key: IdempotencyKey,
        service: Service,
    ) -> ApprovalDecisionResponse:
        del service
        result = services.approval_requests.decide(
            callback_token=body.callback_token.get_secret_value(),
            telegram_user_id=body.telegram_user_id,
            telegram_chat_id=body.telegram_chat_id,
            decision=body.decision,
            idempotency_key=idempotency_key,
            callback_query_present=bool(body.callback_query_id),
            message_external_id=body.message_external_id,
            request_id=request.state.request_id,
        )
        item = result.request
        next_action: Literal["PREPARE", "STOP", "GET_RESULT"] = (
            "STOP"
            if item.status == "REJECTED"
            else "GET_RESULT"
            if item.status == "CONSUMED"
            else "PREPARE"
        )
        return ApprovalDecisionResponse(
            request_id=item.id,
            status=item.status,
            decision=item.decision or body.decision,
            approval_id=item.approval_id,
            publication_id=item.publication_id,
            next_action=next_action,
            replayed=result.replayed,
        )

    @router.post("/orchestration/approval-requests/{request_id_value}/delivery-result")
    def orchestration_delivery_result(
        request_id_value: uuid.UUID,
        body: TelegramDeliveryResult,
        request: Request,
        idempotency_key: IdempotencyKey,
        service: Service,
    ) -> dict[str, object]:
        del service
        delivery = services.orchestration.record_delivery(
            request_id_value=request_id_value,
            phase=body.phase,
            delivery_status=body.delivery_status,
            message_external_id=body.message_external_id,
            safe_error_category=body.safe_error_category,
            idempotency_key=idempotency_key,
            request_id=request.state.request_id,
        )
        return {
            "approval_request_id": delivery.approval_request_id,
            "phase": delivery.phase,
            "delivery_status": delivery.delivery_status,
            "attempts": delivery.attempts,
        }

    @router.post(
        "/orchestration/approval-requests/{request_id_value}/prepare",
        response_model=PublicationResponse,
    )
    def orchestration_prepare(
        request_id_value: uuid.UUID,
        body: OrchestrationPrepare,
        request: Request,
        idempotency_key: IdempotencyKey,
        service: Service,
    ) -> PublicationResponse:
        del service
        return _publication_response(
            services.orchestration.prepare(
                request_id_value=request_id_value,
                connection_id=body.connection_id,
                idempotency_key=idempotency_key,
                request_id=request.state.request_id,
            )
        )

    @router.post(
        "/orchestration/publications/{publication_id}/execute",
        response_model=PublicationResponse,
    )
    async def orchestration_execute(
        publication_id: uuid.UUID,
        body: OrchestrationExecute,
        request: Request,
        idempotency_key: IdempotencyKey,
        service: Service,
    ) -> PublicationResponse:
        del service
        return _publication_response(
            await services.orchestration.execute(
                request_id_value=body.approval_request_id,
                publication_id=publication_id,
                idempotency_key=idempotency_key,
                confirmed=body.confirm_execute,
                request_id=request.state.request_id,
            )
        )

    @router.get(
        "/orchestration/publications/{publication_id}/result",
        response_model=PublicationResponse,
    )
    def orchestration_result(
        publication_id: uuid.UUID,
        service: Service,
    ) -> PublicationResponse:
        del service
        return _publication_response(services.orchestration.get_publication(publication_id))

    return router
