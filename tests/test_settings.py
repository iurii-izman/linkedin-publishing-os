from __future__ import annotations

import pytest
from pydantic import ValidationError

from publisher_api.settings import Settings


def test_settings_accept_valid_configuration(settings_factory: object) -> None:
    settings = settings_factory()  # type: ignore[operator]
    assert settings.linkedin_api_version == "202607"


@pytest.mark.parametrize("version", ["2026-07", "latest", "20267", "20260701"])
def test_settings_reject_invalid_api_version(settings_factory: object, version: str) -> None:
    with pytest.raises(ValidationError, match="YYYYMM"):
        settings_factory(linkedin_api_version=version)  # type: ignore[operator]


def test_settings_reject_extra_scope(settings_factory: object) -> None:
    with pytest.raises(ValidationError, match="exactly"):
        settings_factory(linkedin_scopes="openid profile email w_member_social")  # type: ignore[operator]


def test_settings_reject_placeholder_secret(settings_factory: object) -> None:
    with pytest.raises(ValidationError, match="must be configured"):
        settings_factory(linkedin_client_secret="change-me")  # type: ignore[operator]


def test_settings_reject_invalid_encryption_key(settings_factory: object) -> None:
    with pytest.raises(ValidationError, match="valid Fernet key"):
        settings_factory(token_encryption_key="not-a-fernet-key")  # type: ignore[operator]


def test_settings_reject_short_owner_key(settings_factory: object) -> None:
    with pytest.raises(ValidationError, match="at least 32"):
        settings_factory(stage0_owner_key="too-short")  # type: ignore[operator]


def test_production_requires_https(settings_factory: object) -> None:
    with pytest.raises(ValidationError, match="HTTPS"):
        settings_factory(  # type: ignore[operator]
            app_env="development",
            app_public_url="http://localhost:8000",
            linkedin_redirect_uri="http://localhost:8000/v1/oauth/linkedin/callback",
        )


def test_settings_model_does_not_render_secret(settings_factory: object) -> None:
    settings: Settings = settings_factory()  # type: ignore[operator]
    assert "synthetic-client-secret" not in repr(settings)
