from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote_plus

from cryptography.fernet import Fernet
from pydantic import Field, HttpUrl, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_VERSION_RE = re.compile(r"^\d{6}$")
_SCOPE_SEPARATOR_RE = re.compile(r"[\s,]+")
STAGE0_REQUIRED_SCOPE_ORDER = ("openid", "profile", "w_member_social")
STAGE0_REQUIRED_SCOPES = frozenset(STAGE0_REQUIRED_SCOPE_ORDER)


def normalize_scopes(value: str | list[str] | None) -> list[str]:
    """Return unique decoded scopes from LinkedIn string or list representations."""
    values = [value] if isinstance(value, str) else value or []
    normalized: list[str] = []
    seen: set[str] = set()
    for item in values:
        decoded = unquote_plus(item)
        for scope in _SCOPE_SEPARATOR_RE.split(decoded):
            if scope and scope not in seen:
                normalized.append(scope)
                seen.add(scope)
    return normalized


class Settings(BaseSettings):
    """Configuration shared by the isolated Stage 0 harness and Stage 1 API."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    app_env: str = "development"
    app_public_url: HttpUrl
    log_level: str = "INFO"

    oauth_state_ttl_seconds: int = Field(default=900, ge=60, le=3600)
    linkedin_client_id: SecretStr
    linkedin_client_secret: SecretStr
    linkedin_redirect_uri: HttpUrl
    linkedin_api_base_url: HttpUrl = HttpUrl("https://api.linkedin.com")
    linkedin_authorization_url: HttpUrl = HttpUrl("https://www.linkedin.com/oauth/v2/authorization")
    linkedin_token_url: HttpUrl = HttpUrl("https://www.linkedin.com/oauth/v2/accessToken")
    linkedin_token_introspection_url: HttpUrl = HttpUrl(
        "https://www.linkedin.com/oauth/v2/introspectToken"
    )
    linkedin_userinfo_url: HttpUrl = HttpUrl("https://api.linkedin.com/v2/userinfo")
    linkedin_api_version: str
    linkedin_restli_version: str = "2.0.0"
    linkedin_scopes: str = "openid profile w_member_social"
    linkedin_timeout_connect_seconds: float = Field(default=5.0, gt=0, le=30)
    linkedin_timeout_read_seconds: float = Field(default=20.0, gt=0, le=60)
    linkedin_image_poll_attempts: int = Field(default=10, ge=1, le=30)
    linkedin_image_poll_interval_seconds: float = Field(default=2.0, ge=0, le=30)

    token_encryption_key: SecretStr
    stage0_owner_key: SecretStr
    stage0_token_store_path: Path = Path(".stage0/linkedin-connection.enc")

    database_url: SecretStr = SecretStr(
        "postgresql+psycopg://publisher:publisher@127.0.0.1:5432/publisher"
    )
    database_pool_size: int = Field(default=5, ge=1, le=50)
    database_max_overflow: int = Field(default=5, ge=0, le=50)
    database_connect_timeout: int = Field(default=5, ge=1, le=30)
    app_owner_key: SecretStr | None = None
    stage1_token_key_id: str = Field(default="primary", pattern=r"^[A-Za-z0-9_-]{1,32}$")
    live_linkedin_publishing_enabled: bool = False
    linkedin_publisher_mode: str = "disabled"
    stale_publication_seconds: int = Field(default=300, ge=30, le=86400)

    @field_validator("linkedin_api_version")
    @classmethod
    def validate_api_version(cls, value: str) -> str:
        if not _VERSION_RE.fullmatch(value):
            raise ValueError("must use LinkedIn YYYYMM format")
        return value

    @field_validator("linkedin_scopes")
    @classmethod
    def validate_scopes(cls, value: str) -> str:
        scopes = normalize_scopes(value)
        if set(scopes) != STAGE0_REQUIRED_SCOPES:
            raise ValueError("Stage 0 scopes must be exactly: openid profile w_member_social")
        return " ".join(STAGE0_REQUIRED_SCOPE_ORDER)

    @model_validator(mode="after")
    def validate_urls_and_secrets(self) -> Settings:
        redirect = str(self.linkedin_redirect_uri)
        public = str(self.app_public_url).rstrip("/")
        if not redirect.startswith(f"{public}/"):
            raise ValueError("LINKEDIN_REDIRECT_URI must be below APP_PUBLIC_URL")
        if self.app_env != "test":
            urls = (
                self.app_public_url,
                self.linkedin_redirect_uri,
                self.linkedin_api_base_url,
                self.linkedin_authorization_url,
                self.linkedin_token_url,
                self.linkedin_token_introspection_url,
                self.linkedin_userinfo_url,
            )
            if any(url.scheme != "https" for url in urls):
                raise ValueError("all Stage 0 external URLs must use HTTPS")
        for name, value in (
            ("LINKEDIN_CLIENT_ID", self.linkedin_client_id),
            ("LINKEDIN_CLIENT_SECRET", self.linkedin_client_secret),
            ("TOKEN_ENCRYPTION_KEY", self.token_encryption_key),
            ("STAGE0_OWNER_KEY", self.stage0_owner_key),
        ):
            secret = value.get_secret_value()
            if not secret or secret.startswith("change-me"):
                raise ValueError(f"{name} must be configured")
        try:
            Fernet(self.token_encryption_key.get_secret_value().encode("ascii"))
        except (ValueError, UnicodeEncodeError) as exc:
            raise ValueError("TOKEN_ENCRYPTION_KEY must be a valid Fernet key") from exc
        if len(self.stage0_owner_key.get_secret_value()) < 32:
            raise ValueError("STAGE0_OWNER_KEY must contain at least 32 characters")
        if self.app_owner_key is not None:
            owner_key = self.app_owner_key.get_secret_value()
            if not owner_key or owner_key.startswith("change-me") or len(owner_key) < 32:
                raise ValueError("APP_OWNER_KEY must contain at least 32 configured characters")
        allowed_modes = {
            "disabled",
            "live",
            "fake-success",
            "fake-4xx",
            "fake-timeout",
            "fake-connection-reset",
            "fake-5xx",
            "fake-response-lost",
        }
        if self.linkedin_publisher_mode not in allowed_modes:
            raise ValueError("LINKEDIN_PUBLISHER_MODE is unsupported")
        if self.app_env == "production" and self.linkedin_publisher_mode.startswith("fake-"):
            raise ValueError("fake LinkedIn publishers are forbidden in production")
        return self

    @property
    def timeout(self) -> tuple[float, float]:
        return (self.linkedin_timeout_connect_seconds, self.linkedin_timeout_read_seconds)

    @property
    def owner_key(self) -> SecretStr:
        """Use the dedicated Stage 1 key, with Stage 0 compatibility for old local env files."""
        return self.app_owner_key or self.stage0_owner_key
