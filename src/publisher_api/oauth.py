from __future__ import annotations

import hashlib
import secrets
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from publisher_api.settings import Settings


class OAuthStateError(ValueError):
    pass


class OAuthTokenResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    access_token: SecretStr
    expires_in: int = Field(gt=0)
    scope: str
    token_type: str | None = None
    id_token: SecretStr | None = None
    refresh_token: SecretStr | None = None
    refresh_token_expires_in: int | None = None


class UserInfo(BaseModel):
    model_config = ConfigDict(extra="ignore")

    sub: str = Field(min_length=1, max_length=200)
    name: str | None = None


@dataclass(frozen=True)
class OAuthState:
    value: str
    expires_at: datetime


class InMemoryOAuthStateStore:
    """Single-process, one-time state storage suitable only for the Stage 0 spike."""

    def __init__(self, clock: Callable[[], datetime] | None = None) -> None:
        self._clock = clock or (lambda: datetime.now(UTC))
        self._states: dict[str, datetime] = {}
        self._consumed: set[str] = set()
        self._lock = threading.Lock()

    @staticmethod
    def _digest(state: str) -> str:
        return hashlib.sha256(state.encode("utf-8")).hexdigest()

    def issue(self, ttl_seconds: int) -> OAuthState:
        value = secrets.token_urlsafe(48)
        expires_at = self._clock() + timedelta(seconds=ttl_seconds)
        with self._lock:
            self._states[self._digest(value)] = expires_at
        return OAuthState(value=value, expires_at=expires_at)

    def consume(self, state: str) -> None:
        digest = self._digest(state)
        with self._lock:
            if digest in self._consumed:
                raise OAuthStateError("OAuth state was already consumed")
            expires_at = self._states.pop(digest, None)
            if expires_at is None:
                raise OAuthStateError("OAuth state is unknown")
            self._consumed.add(digest)
        if self._clock() >= expires_at:
            raise OAuthStateError("OAuth state expired")


class OAuthClient:
    def __init__(self, settings: Settings, client: httpx.AsyncClient) -> None:
        self._settings = settings
        self._client = client

    def authorization_url(self, state: str) -> str:
        query = urlencode(
            {
                "response_type": "code",
                "client_id": self._settings.linkedin_client_id.get_secret_value(),
                "redirect_uri": str(self._settings.linkedin_redirect_uri),
                "state": state,
                "scope": self._settings.linkedin_scopes,
            }
        )
        return f"{self._settings.linkedin_authorization_url}?{query}"

    async def exchange_code(self, code: str) -> OAuthTokenResponse:
        response = await self._client.post(
            str(self._settings.linkedin_token_url),
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": self._settings.linkedin_client_id.get_secret_value(),
                "client_secret": self._settings.linkedin_client_secret.get_secret_value(),
                "redirect_uri": str(self._settings.linkedin_redirect_uri),
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        response.raise_for_status()
        return OAuthTokenResponse.model_validate(response.json())

    async def userinfo(self, access_token: SecretStr) -> UserInfo:
        response = await self._client.get(
            str(self._settings.linkedin_userinfo_url),
            headers={"Authorization": f"Bearer {access_token.get_secret_value()}"},
        )
        response.raise_for_status()
        return UserInfo.model_validate(response.json())
