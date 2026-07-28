from __future__ import annotations

import secrets
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import Engine

from publisher_api import __version__
from publisher_api.linkedin import author_urn_from_subject
from publisher_api.oauth import (
    InMemoryOAuthStateStore,
    OAuthClient,
    OAuthStateError,
    OAuthTokenVerificationError,
)
from publisher_api.redaction import redact_text
from publisher_api.settings import STAGE0_REQUIRED_SCOPES, Settings
from publisher_api.stage1_api import create_stage1_router
from publisher_api.stage1_database import (
    create_database_engine,
    create_session_factory,
    database_is_ready,
)
from publisher_api.stage1_domain import DomainError
from publisher_api.stage1_logging import safe_log
from publisher_api.stage1_publisher import TextPublisher, configured_publisher
from publisher_api.stage1_services import Stage1Services
from publisher_api.token_store import EncryptedConnectionStore, StoredConnection


def create_app(
    settings: Settings | None = None,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    state_store: InMemoryOAuthStateStore | None = None,
    stage1_engine: Engine | None = None,
    stage1_publisher: TextPublisher | None = None,
) -> FastAPI:
    active_settings = settings or Settings()  # type: ignore[call-arg]
    states = state_store or InMemoryOAuthStateStore()
    timeout = httpx.Timeout(
        connect=active_settings.linkedin_timeout_connect_seconds,
        read=active_settings.linkedin_timeout_read_seconds,
        write=active_settings.linkedin_timeout_read_seconds,
        pool=active_settings.linkedin_timeout_connect_seconds,
    )
    http_client = httpx.AsyncClient(transport=transport, timeout=timeout)
    oauth = OAuthClient(active_settings, http_client)
    connection_store = EncryptedConnectionStore(
        active_settings.stage0_token_store_path, active_settings.token_encryption_key
    )
    owns_engine = stage1_engine is None
    database_engine = stage1_engine or create_database_engine(active_settings)
    sessions = create_session_factory(database_engine)
    publisher = stage1_publisher or configured_publisher(active_settings)
    stage1 = Stage1Services(sessions, active_settings, publisher)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        yield
        await http_client.aclose()
        if owns_engine:
            database_engine.dispose()

    app = FastAPI(
        title="LinkedIn Publishing OS",
        version=__version__,
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def request_context(
        request: Request,
        call_next: Any,
    ) -> Any:
        started = time.perf_counter()
        supplied = request.headers.get("X-Request-ID", "")
        request.state.request_id = (
            supplied[:100] if supplied and supplied.isprintable() else str(uuid.uuid4())
        )
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        safe_log(
            "http_request_completed",
            request_id=request.state.request_id,
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=round((time.perf_counter() - started) * 1000, 3),
        )
        return response

    @app.exception_handler(DomainError)
    async def domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "code": exc.code,
                "message": exc.message,
                "request_id": request.state.request_id,
                "retryable": exc.retryable,
                "publication_status": (
                    exc.publication_status.value if exc.publication_status else None
                ),
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        del exc
        return JSONResponse(
            status_code=422,
            content={
                "code": "REQUEST_VALIDATION_FAILED",
                "message": "Request validation failed",
                "request_id": request.state.request_id,
                "retryable": False,
                "publication_status": None,
            },
        )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "stage": "1", "version": __version__}

    @app.get("/ready")
    async def ready() -> JSONResponse:
        ready_state, message = database_is_ready(database_engine)
        return JSONResponse(
            status_code=200 if ready_state else 503,
            content={
                "status": "ready" if ready_state else "not_ready",
                "database": ready_state,
                "migrations": ready_state,
                "mutations": ready_state,
                "message": message,
            },
        )

    @app.post("/v1/oauth/linkedin/start")
    async def oauth_start(
        stage0_owner_key: str = Header(alias="X-Stage0-Owner-Key"),
    ) -> dict[str, Any]:
        if not secrets.compare_digest(
            stage0_owner_key,
            active_settings.stage0_owner_key.get_secret_value(),
        ):
            raise HTTPException(status_code=401, detail="Stage 0 owner authentication failed")
        state = states.issue(active_settings.oauth_state_ttl_seconds)
        return {
            "authorization_url": oauth.authorization_url(state.value),
            "expires_at": state.expires_at.isoformat(),
        }

    @app.get("/v1/oauth/linkedin/callback")
    async def oauth_callback(
        state: str = Query(min_length=20),
        code: str | None = None,
        error: str | None = None,
        error_description: str | None = None,
    ) -> JSONResponse:
        del error_description
        try:
            states.consume(state)
        except OAuthStateError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if error is not None:
            safe_error_code = redact_text(error[:100])
            return JSONResponse(
                status_code=400,
                content={"status": "oauth_denied", "safe_error_code": safe_error_code},
            )
        if not code:
            raise HTTPException(status_code=400, detail="OAuth callback code is missing")
        try:
            token = await oauth.exchange_code(code)
            verified_token = await oauth.verify_token_metadata(token)
        except OAuthTokenVerificationError:
            raise HTTPException(
                status_code=403,
                detail="LinkedIn token verification failed for Stage 0",
            ) from None
        except (httpx.HTTPError, ValueError):
            raise HTTPException(
                status_code=502, detail="LinkedIn OAuth completion failed; inspect safe logs"
            ) from None
        granted_scopes = verified_token.granted_scopes
        if not STAGE0_REQUIRED_SCOPES.issubset(granted_scopes):
            raise HTTPException(
                status_code=403,
                detail="LinkedIn did not grant every required Stage 0 scope",
            )
        try:
            userinfo = await oauth.userinfo(token.access_token)
            author_urn = author_urn_from_subject(userinfo.sub)
        except (httpx.HTTPError, ValueError):
            raise HTTPException(
                status_code=502, detail="LinkedIn OAuth completion failed; inspect safe logs"
            ) from None
        expires_at = datetime.now(UTC) + timedelta(seconds=token.expires_in)
        if verified_token.introspected_expires_at is not None:
            expires_at = min(expires_at, verified_token.introspected_expires_at)
        connection_store.save(
            StoredConnection(
                access_token=token.access_token,
                expires_at=expires_at,
                granted_scopes=granted_scopes,
                member_subject=userinfo.sub,
                author_urn=author_urn,
                api_version=active_settings.linkedin_api_version,
            )
        )
        return JSONResponse(
            content={
                "status": "connected_for_stage0",
                "expires_at": expires_at.isoformat(),
                "granted_scopes": granted_scopes,
                "author_urn": author_urn,
                "api_version": active_settings.linkedin_api_version,
                "requires_live_author_validation": True,
            }
        )

    app.include_router(create_stage1_router(active_settings, stage1))
    app.state.stage1_services = stage1
    app.state.database_engine = database_engine
    app.state.stage1_publisher = publisher
    return app
