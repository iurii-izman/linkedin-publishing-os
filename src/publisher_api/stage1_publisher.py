from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import httpx
from pydantic import SecretStr

from publisher_api.linkedin import LinkedInClient, LinkedInError
from publisher_api.settings import Settings


@dataclass(frozen=True, repr=False)
class TextPostCommand:
    access_token: SecretStr
    author_urn: str
    text: str


@dataclass(frozen=True)
class TextPostReceipt:
    identifier: str
    http_status: int = 201


class PublisherFailure(RuntimeError):
    def __init__(
        self,
        *,
        category: str,
        code: str,
        message: str,
        http_status: int | None,
        request_attempted: bool,
        response_received: bool,
        certain_failure: bool,
    ) -> None:
        super().__init__(code)
        self.category = category
        self.code = code
        self.safe_message = message
        self.http_status = http_status
        self.request_attempted = request_attempted
        self.response_received = response_received
        self.certain_failure = certain_failure


class TextPublisher(Protocol):
    available: bool

    async def create_text_post(self, command: TextPostCommand) -> TextPostReceipt: ...


class FakeLinkedInPublisher:
    """Deterministic offline adapter; it never opens a network connection."""

    def __init__(self, outcome: str = "success") -> None:
        self.available = True
        self.outcome = outcome
        self.call_count = 0

    async def create_text_post(self, command: TextPostCommand) -> TextPostReceipt:
        del command
        self.call_count += 1
        if self.outcome == "success":
            return TextPostReceipt("urn:li:share:synthetic-stage1-post")
        if self.outcome == "4xx":
            raise PublisherFailure(
                category="VALIDATION",
                code="LINKEDIN_REQUEST_REJECTED",
                message="LinkedIn rejected the request",
                http_status=400,
                request_attempted=True,
                response_received=True,
                certain_failure=True,
            )
        mapping = {
            "timeout": ("NETWORK", "LINKEDIN_TIMEOUT", None, False),
            "connection-reset": ("NETWORK", "LINKEDIN_CONNECTION_RESET", None, False),
            "5xx": ("SERVER", "LINKEDIN_SERVER_ERROR", 503, True),
            "response-lost": ("NETWORK", "LINKEDIN_RESPONSE_LOST", None, False),
        }
        category, code, status, response_received = mapping[self.outcome]
        raise PublisherFailure(
            category=category,
            code=code,
            message="Final LinkedIn post outcome is uncertain",
            http_status=status,
            request_attempted=True,
            response_received=response_received,
            certain_failure=False,
        )


class LiveLinkedInPublisher:
    def __init__(self, settings: Settings) -> None:
        self.available = True
        self._settings = settings

    async def create_text_post(self, command: TextPostCommand) -> TextPostReceipt:
        timeout = httpx.Timeout(
            connect=self._settings.linkedin_timeout_connect_seconds,
            read=self._settings.linkedin_timeout_read_seconds,
            write=self._settings.linkedin_timeout_read_seconds,
            pool=self._settings.linkedin_timeout_connect_seconds,
        )
        try:
            async with httpx.AsyncClient(
                base_url=str(self._settings.linkedin_api_base_url), timeout=timeout
            ) as client:
                receipt = await LinkedInClient(self._settings, client).create_text_post(
                    command.access_token.get_secret_value(),
                    command.author_urn,
                    command.text,
                )
        except LinkedInError as exc:
            record = exc.record
            status = record.http_status
            certain = bool(
                record.response_received
                and status is not None
                and 400 <= status < 500
                and status not in {408, 409, 425, 429}
            )
            raise PublisherFailure(
                category=record.error_category.value,
                code=exc.safe_code,
                message=record.sanitized_message or "LinkedIn request failed",
                http_status=status,
                request_attempted=record.request_attempted,
                response_received=record.response_received,
                certain_failure=certain,
            ) from None
        return TextPostReceipt(receipt.post_urn, receipt.status_code)


class DisabledLinkedInPublisher:
    available = False

    async def create_text_post(self, command: TextPostCommand) -> TextPostReceipt:
        del command
        raise AssertionError("Disabled LinkedIn publisher must not be called")


def configured_publisher(settings: Settings) -> TextPublisher:
    mode = settings.linkedin_publisher_mode
    if mode.startswith("fake-"):
        if settings.app_env not in {"test", "development"}:
            raise ValueError("Fake LinkedIn publisher is unavailable in this environment")
        return FakeLinkedInPublisher(mode.removeprefix("fake-"))
    if mode == "live":
        if not settings.live_linkedin_publishing_enabled:
            return DisabledLinkedInPublisher()
        return LiveLinkedInPublisher(settings)
    return DisabledLinkedInPublisher()
