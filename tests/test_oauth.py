from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi import FastAPI
from pydantic import ValidationError

from publisher_api.main import create_app
from publisher_api.oauth import (
    InMemoryOAuthStateStore,
    OAuthClient,
    OAuthStateError,
    OAuthTokenResponse,
)
from publisher_api.settings import normalize_scopes
from publisher_api.token_store import EncryptedConnectionStore


@asynccontextmanager
async def app_client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="https://stage0.example.test",
        ) as client:
            yield client


def test_oauth_state_has_high_entropy_and_is_one_time() -> None:
    store = InMemoryOAuthStateStore()
    state = store.issue(900)
    assert len(state.value) >= 64
    store.consume(state.value)
    with pytest.raises(OAuthStateError, match="already consumed"):
        store.consume(state.value)


def test_oauth_state_expires() -> None:
    current = datetime(2026, 7, 23, tzinfo=UTC)
    store = InMemoryOAuthStateStore(clock=lambda: current)
    state = store.issue(60)
    current += timedelta(seconds=60)
    with pytest.raises(OAuthStateError, match="expired"):
        store.consume(state.value)


def test_authorization_url_has_exact_scopes_and_state(settings_factory: object) -> None:
    settings = settings_factory()  # type: ignore[operator]
    client = OAuthClient(settings, httpx.AsyncClient())
    url = client.authorization_url("synthetic-state")
    query = parse_qs(urlsplit(url).query)
    assert query["scope"] == ["openid profile w_member_social"]
    assert query["state"] == ["synthetic-state"]
    assert query["redirect_uri"] == [str(settings.linkedin_redirect_uri)]


@pytest.mark.parametrize(
    ("raw_scopes", "expected"),
    [
        ("openid profile w_member_social", ["openid", "profile", "w_member_social"]),
        ("openid,profile,w_member_social", ["openid", "profile", "w_member_social"]),
        ("openid%20profile%20w_member_social", ["openid", "profile", "w_member_social"]),
        (["openid", "profile", "w_member_social"], ["openid", "profile", "w_member_social"]),
        (
            "openid profile email w_member_social",
            ["openid", "profile", "email", "w_member_social"],
        ),
    ],
)
def test_normalize_scopes_accepts_linkedin_representations(
    raw_scopes: str | list[str], expected: list[str]
) -> None:
    assert normalize_scopes(raw_scopes) == expected


@pytest.mark.asyncio
async def test_oauth_start_requires_owner_key(settings_factory: object) -> None:
    settings = settings_factory()  # type: ignore[operator]
    async with app_client(create_app(settings)) as client:
        unauthorized = await client.post("/v1/oauth/linkedin/start")
        wrong = await client.post(
            "/v1/oauth/linkedin/start",
            headers={"X-Stage0-Owner-Key": "wrong"},
        )
        accepted = await client.post(
            "/v1/oauth/linkedin/start",
            headers={"X-Stage0-Owner-Key": settings.stage0_owner_key.get_secret_value()},
        )
    assert unauthorized.status_code == 422
    assert wrong.status_code == 401
    assert accepted.status_code == 200
    assert "authorization_url" in accepted.json()


def test_token_response_parses_documented_fields_without_exposing_token() -> None:
    token = OAuthTokenResponse.model_validate(
        {
            "access_token": "AQ-synthetic-secret-token-value",
            "expires_in": 5_184_000,
            "scope": "openid profile w_member_social",
        }
    )
    assert token.expires_in == 5_184_000
    assert "AQ-synthetic-secret-token-value" not in repr(token)


def test_token_response_allows_scope_to_be_omitted_without_exposing_token() -> None:
    token = OAuthTokenResponse.model_validate(
        {
            "access_token": "AQ-synthetic-secret-token-value",
            "expires_in": 5_184_000,
        }
    )
    assert token.scope is None
    assert "AQ-synthetic-secret-token-value" not in repr(token)


def test_token_response_rejects_missing_expiry() -> None:
    with pytest.raises(ValidationError):
        OAuthTokenResponse.model_validate(
            {"access_token": "AQ-synthetic-secret-token-value", "scope": "openid"}
        )


@pytest.mark.asyncio
async def test_missing_callback_code_consumes_state(settings_factory: object) -> None:
    settings = settings_factory()  # type: ignore[operator]
    store = InMemoryOAuthStateStore()
    state = store.issue(900)
    async with app_client(create_app(settings, state_store=store)) as client:
        response = await client.get("/v1/oauth/linkedin/callback", params={"state": state.value})
        replay = await client.get("/v1/oauth/linkedin/callback", params={"state": state.value})
    assert response.status_code == 400
    assert replay.status_code == 400
    assert replay.json()["detail"] == "OAuth state was already consumed"


@pytest.mark.asyncio
async def test_oauth_error_callback_is_safe_and_consumes_state(
    settings_factory: object,
) -> None:
    settings = settings_factory()  # type: ignore[operator]
    store = InMemoryOAuthStateStore()
    state = store.issue(900)
    async with app_client(create_app(settings, state_store=store)) as client:
        response = await client.get(
            "/v1/oauth/linkedin/callback",
            params={
                "state": state.value,
                "error": "user_cancelled_authorize",
                "error_description": "AQ-synthetic-secret-token-value",
            },
        )
    assert response.status_code == 400
    assert response.json() == {
        "status": "oauth_denied",
        "safe_error_code": "user_cancelled_authorize",
    }
    assert "AQ-synthetic" not in response.text


@pytest.mark.asyncio
async def test_successful_callback_stores_encrypted_connection(
    settings_factory: object,
) -> None:
    settings = settings_factory()  # type: ignore[operator]
    store = InMemoryOAuthStateStore()
    state = store.issue(900)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/accessToken"):
            return httpx.Response(
                200,
                json={
                    "access_token": "AQ-synthetic-secret-token-value",
                    "expires_in": 3600,
                    "scope": "openid profile w_member_social",
                },
            )
        return httpx.Response(200, json={"sub": "member_123", "name": "Synthetic Owner"})

    app = create_app(settings, transport=httpx.MockTransport(handler), state_store=store)
    async with app_client(app) as client:
        response = await client.get(
            "/v1/oauth/linkedin/callback",
            params={"state": state.value, "code": "synthetic-code"},
        )
    assert response.status_code == 200
    assert response.json()["author_urn"] == "urn:li:person:member_123"
    ciphertext = settings.stage0_token_store_path.read_bytes()
    assert b"AQ-synthetic-secret-token-value" not in ciphertext
    assert "AQ-synthetic-secret-token-value" not in response.text
    stored = EncryptedConnectionStore(
        settings.stage0_token_store_path, settings.token_encryption_key
    ).load()
    assert stored.access_token.get_secret_value() == "AQ-synthetic-secret-token-value"


@pytest.mark.parametrize(
    "returned_scopes",
    [
        "openid,profile,w_member_social",
        "openid%20profile%20w_member_social",
        ["openid", "profile", "w_member_social"],
        "openid profile email w_member_social",
    ],
)
@pytest.mark.asyncio
async def test_callback_accepts_normalized_and_additional_granted_scopes(
    settings_factory: object,
    returned_scopes: str | list[str],
) -> None:
    settings = settings_factory()  # type: ignore[operator]
    store = InMemoryOAuthStateStore()
    state = store.issue(900)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/accessToken"):
            return httpx.Response(
                200,
                json={
                    "access_token": "AQ-synthetic-secret-token-value",
                    "expires_in": 3600,
                    "scope": returned_scopes,
                },
            )
        return httpx.Response(200, json={"sub": "member_123"})

    app = create_app(settings, transport=httpx.MockTransport(handler), state_store=store)
    async with app_client(app) as client:
        response = await client.get(
            "/v1/oauth/linkedin/callback",
            params={"state": state.value, "code": "synthetic-code"},
        )

    assert response.status_code == 200
    assert settings.stage0_token_store_path.exists()
    assert set(response.json()["granted_scopes"]) >= {
        "openid",
        "profile",
        "w_member_social",
    }


@pytest.mark.asyncio
async def test_missing_token_scope_uses_successful_introspection(
    settings_factory: object,
) -> None:
    settings = settings_factory()  # type: ignore[operator]
    store = InMemoryOAuthStateStore()
    state = store.issue(900)
    introspection_seen = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal introspection_seen
        if request.url.path.endswith("/accessToken"):
            return httpx.Response(
                200,
                json={
                    "access_token": "AQ-synthetic-secret-token-value",
                    "expires_in": 3600,
                },
            )
        if request.url.path.endswith("/introspectToken"):
            introspection_seen = True
            form = parse_qs(request.content.decode("ascii"))
            assert request.method == "POST"
            assert form["client_id"] == ["synthetic-client-id"]
            assert form["client_secret"] == ["synthetic-client-secret"]
            assert form["token"] == ["AQ-synthetic-secret-token-value"]
            return httpx.Response(
                200,
                json={
                    "active": True,
                    "client_id": "synthetic-client-id",
                    "expires_at": int((datetime.now(UTC) + timedelta(hours=1)).timestamp()),
                    "scope": "openid,profile,w_member_social",
                },
            )
        return httpx.Response(200, json={"sub": "member_123"})

    app = create_app(settings, transport=httpx.MockTransport(handler), state_store=store)
    async with app_client(app) as client:
        response = await client.get(
            "/v1/oauth/linkedin/callback",
            params={"state": state.value, "code": "synthetic-code"},
        )

    assert response.status_code == 200
    assert introspection_seen
    assert response.json()["granted_scopes"] == ["openid", "profile", "w_member_social"]
    assert settings.stage0_token_store_path.exists()


@pytest.mark.asyncio
async def test_inactive_introspected_token_is_rejected_without_persistence(
    settings_factory: object,
) -> None:
    settings = settings_factory()  # type: ignore[operator]
    store = InMemoryOAuthStateStore()
    state = store.issue(900)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/accessToken"):
            return httpx.Response(
                200,
                json={
                    "access_token": "AQ-synthetic-secret-token-value",
                    "expires_in": 3600,
                },
            )
        if request.url.path.endswith("/introspectToken"):
            return httpx.Response(
                200,
                json={
                    "active": False,
                    "client_id": "synthetic-client-id",
                    "scope": "openid,profile,w_member_social",
                },
            )
        pytest.fail("UserInfo must not be called for an inactive token")

    app = create_app(settings, transport=httpx.MockTransport(handler), state_store=store)
    async with app_client(app) as client:
        response = await client.get(
            "/v1/oauth/linkedin/callback",
            params={"state": state.value, "code": "synthetic-code"},
        )

    assert response.status_code == 403
    assert not settings.stage0_token_store_path.exists()
    assert "AQ-synthetic-secret-token-value" not in response.text


@pytest.mark.asyncio
async def test_introspection_client_mismatch_is_rejected(
    settings_factory: object,
) -> None:
    settings = settings_factory()  # type: ignore[operator]
    store = InMemoryOAuthStateStore()
    state = store.issue(900)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/accessToken"):
            return httpx.Response(
                200,
                json={
                    "access_token": "AQ-synthetic-secret-token-value",
                    "expires_in": 3600,
                },
            )
        if request.url.path.endswith("/introspectToken"):
            return httpx.Response(
                200,
                json={
                    "active": True,
                    "client_id": "different-client-id",
                    "scope": "openid,profile,w_member_social",
                },
            )
        pytest.fail("UserInfo must not be called for a token issued to another client")

    app = create_app(settings, transport=httpx.MockTransport(handler), state_store=store)
    async with app_client(app) as client:
        response = await client.get(
            "/v1/oauth/linkedin/callback",
            params={"state": state.value, "code": "synthetic-code"},
        )

    assert response.status_code == 403
    assert not settings.stage0_token_store_path.exists()


@pytest.mark.asyncio
async def test_callback_rejects_missing_required_scope_without_exposing_token(
    settings_factory: object,
    caplog: pytest.LogCaptureFixture,
) -> None:
    settings = settings_factory()  # type: ignore[operator]
    store = InMemoryOAuthStateStore()
    state = store.issue(900)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/accessToken"):
            return httpx.Response(
                200,
                json={
                    "access_token": "AQ-synthetic-secret-token-value",
                    "expires_in": 3600,
                    "scope": "openid,profile",
                },
            )
        return httpx.Response(200, json={"sub": "member_123"})

    app = create_app(settings, transport=httpx.MockTransport(handler), state_store=store)
    async with app_client(app) as client:
        response = await client.get(
            "/v1/oauth/linkedin/callback",
            params={"state": state.value, "code": "synthetic-code"},
        )
    assert response.status_code == 403
    assert not settings.stage0_token_store_path.exists()
    assert "AQ-synthetic-secret-token-value" not in response.text
    assert "AQ-synthetic-secret-token-value" not in caplog.text
