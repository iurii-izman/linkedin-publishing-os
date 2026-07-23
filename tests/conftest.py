from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
from cryptography.fernet import Fernet

from publisher_api.settings import Settings


@pytest.fixture
def settings_factory(tmp_path: Path) -> Callable[..., Settings]:
    def factory(**overrides: object) -> Settings:
        values: dict[str, object] = {
            "app_env": "test",
            "app_public_url": "https://stage0.example.test",
            "linkedin_client_id": "synthetic-client-id",
            "linkedin_client_secret": "synthetic-client-secret",
            "linkedin_redirect_uri": ("https://stage0.example.test/v1/oauth/linkedin/callback"),
            "linkedin_api_base_url": "https://api.linkedin.test",
            "linkedin_authorization_url": "https://auth.linkedin.test/oauth/v2/authorization",
            "linkedin_token_url": "https://auth.linkedin.test/oauth/v2/accessToken",
            "linkedin_userinfo_url": "https://api.linkedin.test/v2/userinfo",
            "linkedin_api_version": "202607",
            "token_encryption_key": Fernet.generate_key().decode("ascii"),
            "stage0_owner_key": "synthetic-stage0-owner-key-with-32-characters",
            "stage0_token_store_path": tmp_path / "connection.enc",
            "linkedin_image_poll_interval_seconds": 0,
        }
        values.update(overrides)
        return Settings.model_validate(values)

    return factory


@pytest.fixture
def request_factory() -> Callable[[str, str], httpx.Request]:
    def factory(
        method: str = "POST", url: str = "https://api.linkedin.test/rest/posts"
    ) -> httpx.Request:
        return httpx.Request(method, url)

    return factory
