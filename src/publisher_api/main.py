from __future__ import annotations

import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import JSONResponse

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
from publisher_api.token_store import EncryptedConnectionStore, StoredConnection


def create_app(
    settings: Settings | None = None,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    state_store: InMemoryOAuthStateStore | None = None,
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

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        yield
        await http_client.aclose()

    app = FastAPI(
        title="LinkedIn Publishing OS Stage 0",
        version=__version__,
        lifespan=lifespan,
    )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "stage": "0", "version": __version__}

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

    return app
