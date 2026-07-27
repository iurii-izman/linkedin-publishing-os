from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from urllib.parse import quote, urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

from publisher_api.redaction import redact_text
from publisher_api.settings import Settings

_SUBJECT_RE = re.compile(r"^[A-Za-z0-9_-]{1,200}$")
_PERSON_URN_RE = re.compile(r"^urn:li:person:[A-Za-z0-9_-]{1,200}$")
_IMAGE_URN_RE = re.compile(r"^urn:li:image:[A-Za-z0-9_-]{1,300}$")
_POST_URN_RE = re.compile(r"^urn:li:(?:share|ugcPost):[A-Za-z0-9_-]+$")


class LinkedInRequestStage(StrEnum):
    INITIALIZE_UPLOAD = "INITIALIZE_UPLOAD"
    BINARY_UPLOAD = "BINARY_UPLOAD"
    IMAGE_STATUS = "IMAGE_STATUS"
    FINAL_POST = "FINAL_POST"


class LinkedInErrorCategory(StrEnum):
    VALIDATION = "VALIDATION"
    AUTHENTICATION = "AUTHENTICATION"
    PERMISSION = "PERMISSION"
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"
    API_VERSION = "API_VERSION"
    RATE_LIMIT = "RATE_LIMIT"
    SERVER = "SERVER"
    NETWORK = "NETWORK"
    MALFORMED_RESPONSE = "MALFORMED_RESPONSE"
    LOCAL_VALIDATION = "LOCAL_VALIDATION"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class SafeLinkedInErrorRecord:
    stage: LinkedInRequestStage
    http_status: int | None
    error_category: LinkedInErrorCategory
    service_error_code: int | str | None
    linkedin_error_code: int | str | None
    sanitized_message: str | None
    retryable: bool
    request_attempted: bool
    response_received: bool


def _safe_error_record(
    stage: LinkedInRequestStage,
    category: LinkedInErrorCategory,
    *,
    http_status: int | None = None,
    service_error_code: int | str | None = None,
    linkedin_error_code: int | str | None = None,
    message: str | None = None,
    retryable: bool = False,
    request_attempted: bool,
    response_received: bool,
) -> SafeLinkedInErrorRecord:
    sanitized_message = redact_text(message)[:300] if message else None
    return SafeLinkedInErrorRecord(
        stage=stage,
        http_status=http_status,
        error_category=category,
        service_error_code=service_error_code,
        linkedin_error_code=linkedin_error_code,
        sanitized_message=sanitized_message,
        retryable=retryable,
        request_attempted=request_attempted,
        response_received=response_received,
    )


class LinkedInError(RuntimeError):
    def __init__(self, safe_code: str, record: SafeLinkedInErrorRecord) -> None:
        super().__init__(safe_code)
        self.safe_code = safe_code
        self.record = record
        self.status_code = record.http_status


class SafePreSendError(LinkedInError):
    pass


class PublishUncertainError(LinkedInError):
    pass


class ImageReservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    image_urn: str
    upload_url: str
    upload_url_expires_at: int
    http_status: int = 200


class PublishReceipt(BaseModel):
    post_urn: str
    status_code: int = 201


class ImageStatus(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    status: str


@dataclass(frozen=True)
class PreparedRequest:
    method: str
    path: str
    headers: dict[str, str]
    json_body: dict[str, Any]


def author_urn_from_subject(subject: str) -> str:
    if not _SUBJECT_RE.fullmatch(subject):
        raise ValueError("OIDC subject is not safe to embed in a person URN")
    return f"urn:li:person:{subject}"


def validate_author_urn(author_urn: str) -> str:
    if not _PERSON_URN_RE.fullmatch(author_urn):
        raise ValueError("invalid LinkedIn person URN")
    return author_urn


def _safe_error_scalar(value: object) -> int | str | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", value):
        return value
    return None


def _response_error_details(
    response: httpx.Response,
) -> tuple[int | str | None, int | str | None, str | None]:
    try:
        payload = response.json()
    except (ValueError, TypeError):
        return None, None, None
    if not isinstance(payload, dict):
        return None, None, None
    service_error_code = _safe_error_scalar(payload.get("serviceErrorCode"))
    linkedin_error_code = _safe_error_scalar(payload.get("code"))
    raw_message = payload.get("message")
    message = raw_message if isinstance(raw_message, str) else None
    return service_error_code, linkedin_error_code, message


def _status_category(status_code: int) -> LinkedInErrorCategory:
    return {
        400: LinkedInErrorCategory.VALIDATION,
        401: LinkedInErrorCategory.AUTHENTICATION,
        403: LinkedInErrorCategory.PERMISSION,
        404: LinkedInErrorCategory.NOT_FOUND,
        409: LinkedInErrorCategory.CONFLICT,
        426: LinkedInErrorCategory.API_VERSION,
        429: LinkedInErrorCategory.RATE_LIMIT,
        500: LinkedInErrorCategory.SERVER,
        503: LinkedInErrorCategory.SERVER,
    }.get(status_code, LinkedInErrorCategory.UNKNOWN)


class LinkedInClient:
    def __init__(
        self,
        settings: Settings,
        client: httpx.AsyncClient,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._settings = settings
        self._client = client
        self._sleep = sleep

    def _headers(self, access_token: str, *, content_type: bool = True) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Linkedin-Version": self._settings.linkedin_api_version,
            "X-Restli-Protocol-Version": self._settings.linkedin_restli_version,
        }
        if content_type:
            headers["Content-Type"] = "application/json"
        return headers

    @staticmethod
    def text_payload(author_urn: str, text: str) -> dict[str, Any]:
        validate_author_urn(author_urn)
        if not text.strip():
            raise ValueError("post text must not be empty")
        return {
            "author": author_urn,
            "commentary": text,
            "visibility": "PUBLIC",
            "distribution": {
                "feedDistribution": "MAIN_FEED",
                "targetEntities": [],
                "thirdPartyDistributionChannels": [],
            },
            "lifecycleState": "PUBLISHED",
            "isReshareDisabledByAuthor": False,
        }

    @classmethod
    def image_payload(
        cls, author_urn: str, text: str, image_urn: str, alt_text: str
    ) -> dict[str, Any]:
        payload = cls.text_payload(author_urn, text)
        if not _IMAGE_URN_RE.fullmatch(image_urn):
            raise ValueError("invalid LinkedIn image URN")
        if not alt_text.strip():
            raise ValueError("image alt text must not be empty")
        payload["content"] = {"media": {"id": image_urn, "altText": alt_text}}
        return payload

    def prepare_text(self, author_urn: str, text: str) -> PreparedRequest:
        return PreparedRequest(
            method="POST",
            path="/rest/posts",
            headers={
                "Linkedin-Version": self._settings.linkedin_api_version,
                "X-Restli-Protocol-Version": self._settings.linkedin_restli_version,
                "Content-Type": "application/json",
                "Authorization": "Bearer [REDACTED]",
            },
            json_body=self.text_payload(author_urn, text),
        )

    def prepare_image_initialize(self, author_urn: str) -> PreparedRequest:
        validate_author_urn(author_urn)
        return PreparedRequest(
            method="POST",
            path="/rest/images?action=initializeUpload",
            headers={
                "Linkedin-Version": self._settings.linkedin_api_version,
                "X-Restli-Protocol-Version": self._settings.linkedin_restli_version,
                "Content-Type": "application/json",
                "Authorization": "Bearer [REDACTED]",
            },
            json_body={"initializeUploadRequest": {"owner": author_urn}},
        )

    async def create_text_post(
        self, access_token: str, author_urn: str, text: str
    ) -> PublishReceipt:
        return await self._create_final_post(access_token, self.text_payload(author_urn, text))

    async def initialize_image(self, access_token: str, author_urn: str) -> ImageReservation:
        validate_author_urn(author_urn)
        try:
            response = await self._client.post(
                "/rest/images?action=initializeUpload",
                headers=self._headers(access_token),
                json={"initializeUploadRequest": {"owner": author_urn}},
            )
        except httpx.RequestError as exc:
            raise LinkedInError(
                "IMAGE_INITIALIZE_NETWORK_ERROR",
                _safe_error_record(
                    LinkedInRequestStage.INITIALIZE_UPLOAD,
                    LinkedInErrorCategory.NETWORK,
                    request_attempted=True,
                    response_received=False,
                ),
            ) from exc
        self._raise_for_status(response, stage=LinkedInRequestStage.INITIALIZE_UPLOAD)
        try:
            value = response.json()["value"]
            reservation = ImageReservation(
                image_urn=value["image"],
                upload_url=value["uploadUrl"],
                upload_url_expires_at=value["uploadUrlExpiresAt"],
                http_status=response.status_code,
            )
        except (KeyError, TypeError, ValidationError) as exc:
            raise LinkedInError(
                "IMAGE_INITIALIZE_MALFORMED_RESPONSE",
                _safe_error_record(
                    LinkedInRequestStage.INITIALIZE_UPLOAD,
                    LinkedInErrorCategory.MALFORMED_RESPONSE,
                    http_status=response.status_code,
                    request_attempted=True,
                    response_received=True,
                ),
            ) from exc
        if not _IMAGE_URN_RE.fullmatch(reservation.image_urn):
            raise LinkedInError(
                "IMAGE_INITIALIZE_INVALID_URN",
                _safe_error_record(
                    LinkedInRequestStage.INITIALIZE_UPLOAD,
                    LinkedInErrorCategory.MALFORMED_RESPONSE,
                    http_status=response.status_code,
                    request_attempted=True,
                    response_received=True,
                ),
            )
        self._validate_upload_url(
            reservation.upload_url,
            stage=LinkedInRequestStage.INITIALIZE_UPLOAD,
            request_attempted=True,
            response_received=True,
        )
        return reservation

    async def upload_image(
        self, access_token: str, reservation: ImageReservation, data: bytes, content_type: str
    ) -> int:
        self._validate_upload_url(
            reservation.upload_url,
            stage=LinkedInRequestStage.BINARY_UPLOAD,
            request_attempted=False,
            response_received=False,
        )
        if not data:
            raise ValueError("image data must not be empty")
        try:
            response = await self._client.put(
                reservation.upload_url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": content_type,
                },
                content=data,
            )
        except httpx.RequestError as exc:
            raise LinkedInError(
                "IMAGE_UPLOAD_NETWORK_ERROR",
                _safe_error_record(
                    LinkedInRequestStage.BINARY_UPLOAD,
                    LinkedInErrorCategory.NETWORK,
                    request_attempted=True,
                    response_received=False,
                ),
            ) from exc
        if response.status_code not in {200, 201}:
            self._raise_for_status(response, stage=LinkedInRequestStage.BINARY_UPLOAD)
        return response.status_code

    async def upload_image_once_and_wait(
        self,
        access_token: str,
        reservation: ImageReservation,
        data: bytes,
        content_type: str,
    ) -> None:
        try:
            await self.upload_image(access_token, reservation, data, content_type)
        except LinkedInError as exc:
            if exc.safe_code not in {
                "IMAGE_UPLOAD_NETWORK_ERROR",
                "LINKEDIN_SERVER_ERROR",
                "LINKEDIN_UNAVAILABLE",
            }:
                raise
            # The upload session already exists. Reconcile that image URN rather
            # than creating another session or sending the binary a second time.
            try:
                await self.wait_for_image(access_token, reservation.image_urn)
            except LinkedInError as status_exc:
                raise LinkedInError("MEDIA_UPLOAD_UNCERTAIN", status_exc.record) from status_exc
        else:
            await self.wait_for_image(access_token, reservation.image_urn)

    async def get_image_status(self, access_token: str, image_urn: str) -> ImageStatus:
        if not _IMAGE_URN_RE.fullmatch(image_urn):
            raise ValueError("invalid LinkedIn image URN")
        try:
            encoded_image_urn = quote(image_urn, safe="")
            response = await self._client.get(
                f"/rest/images/{encoded_image_urn}",
                headers=self._headers(access_token, content_type=False),
            )
        except httpx.RequestError as exc:
            raise LinkedInError(
                "IMAGE_STATUS_NETWORK_ERROR",
                _safe_error_record(
                    LinkedInRequestStage.IMAGE_STATUS,
                    LinkedInErrorCategory.NETWORK,
                    retryable=True,
                    request_attempted=True,
                    response_received=False,
                ),
            ) from exc
        self._raise_for_status(response, stage=LinkedInRequestStage.IMAGE_STATUS)
        try:
            return ImageStatus.model_validate(response.json())
        except ValidationError as exc:
            raise LinkedInError(
                "IMAGE_STATUS_MALFORMED_RESPONSE",
                _safe_error_record(
                    LinkedInRequestStage.IMAGE_STATUS,
                    LinkedInErrorCategory.MALFORMED_RESPONSE,
                    http_status=response.status_code,
                    request_attempted=True,
                    response_received=True,
                ),
            ) from exc

    async def wait_for_image(self, access_token: str, image_urn: str) -> None:
        for attempt in range(self._settings.linkedin_image_poll_attempts):
            status = await self.get_image_status(access_token, image_urn)
            if status.status == "AVAILABLE":
                return
            if status.status == "PROCESSING_FAILED":
                raise LinkedInError(
                    "IMAGE_PROCESSING_FAILED",
                    _safe_error_record(
                        LinkedInRequestStage.IMAGE_STATUS,
                        LinkedInErrorCategory.VALIDATION,
                        message="LinkedIn image processing failed",
                        request_attempted=True,
                        response_received=True,
                    ),
                )
            if status.status not in {"WAITING_UPLOAD", "PROCESSING"}:
                raise LinkedInError(
                    "IMAGE_STATUS_UNKNOWN",
                    _safe_error_record(
                        LinkedInRequestStage.IMAGE_STATUS,
                        LinkedInErrorCategory.MALFORMED_RESPONSE,
                        message="LinkedIn returned an unsupported image status",
                        request_attempted=True,
                        response_received=True,
                    ),
                )
            if attempt + 1 < self._settings.linkedin_image_poll_attempts:
                await self._sleep(self._settings.linkedin_image_poll_interval_seconds)
        raise LinkedInError(
            "IMAGE_PROCESSING_TIMEOUT",
            _safe_error_record(
                LinkedInRequestStage.IMAGE_STATUS,
                LinkedInErrorCategory.NETWORK,
                retryable=True,
                request_attempted=True,
                response_received=True,
            ),
        )

    async def create_image_post(
        self,
        access_token: str,
        author_urn: str,
        text: str,
        image_urn: str,
        alt_text: str,
    ) -> PublishReceipt:
        return await self._create_final_post(
            access_token, self.image_payload(author_urn, text, image_urn, alt_text)
        )

    async def _create_final_post(
        self, access_token: str, payload: dict[str, Any]
    ) -> PublishReceipt:
        try:
            response = await self._client.post(
                "/rest/posts", headers=self._headers(access_token), json=payload
            )
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout) as exc:
            raise SafePreSendError(
                "FINAL_REQUEST_NOT_SENT",
                _safe_error_record(
                    LinkedInRequestStage.FINAL_POST,
                    LinkedInErrorCategory.NETWORK,
                    retryable=True,
                    request_attempted=False,
                    response_received=False,
                ),
            ) from exc
        except httpx.RequestError as exc:
            raise PublishUncertainError(
                "FINAL_REQUEST_OUTCOME_UNCERTAIN",
                _safe_error_record(
                    LinkedInRequestStage.FINAL_POST,
                    LinkedInErrorCategory.NETWORK,
                    request_attempted=True,
                    response_received=False,
                ),
            ) from exc
        self._raise_for_status(
            response,
            stage=LinkedInRequestStage.FINAL_POST,
            final_request=True,
        )
        if response.status_code != 201:
            raise LinkedInError(
                "POST_UNEXPECTED_SUCCESS_STATUS",
                _safe_error_record(
                    LinkedInRequestStage.FINAL_POST,
                    LinkedInErrorCategory.UNKNOWN,
                    http_status=response.status_code,
                    request_attempted=True,
                    response_received=True,
                ),
            )
        post_urn = response.headers.get("x-restli-id")
        if not post_urn or not _POST_URN_RE.fullmatch(post_urn):
            raise PublishUncertainError(
                "POST_CREATED_ID_MISSING",
                _safe_error_record(
                    LinkedInRequestStage.FINAL_POST,
                    LinkedInErrorCategory.MALFORMED_RESPONSE,
                    http_status=201,
                    request_attempted=True,
                    response_received=True,
                ),
            )
        return PublishReceipt(post_urn=post_urn)

    @staticmethod
    def _validate_upload_url(
        upload_url: str,
        *,
        stage: LinkedInRequestStage,
        request_attempted: bool,
        response_received: bool,
    ) -> None:
        parsed = urlsplit(upload_url)
        if parsed.scheme != "https" or parsed.hostname != "www.linkedin.com":
            raise LinkedInError(
                "UNTRUSTED_UPLOAD_URL",
                _safe_error_record(
                    stage,
                    LinkedInErrorCategory.LOCAL_VALIDATION,
                    request_attempted=request_attempted,
                    response_received=response_received,
                ),
            )
        if not parsed.path.startswith("/dms-uploads/"):
            raise LinkedInError(
                "UNTRUSTED_UPLOAD_URL",
                _safe_error_record(
                    stage,
                    LinkedInErrorCategory.LOCAL_VALIDATION,
                    request_attempted=request_attempted,
                    response_received=response_received,
                ),
            )

    @staticmethod
    def _raise_for_status(
        response: httpx.Response,
        *,
        stage: LinkedInRequestStage,
        final_request: bool = False,
    ) -> None:
        if 200 <= response.status_code < 300:
            return
        service_error_code, linkedin_error_code, message = _response_error_details(response)
        record = _safe_error_record(
            stage,
            _status_category(response.status_code),
            http_status=response.status_code,
            service_error_code=service_error_code,
            linkedin_error_code=linkedin_error_code,
            message=message,
            retryable=not final_request and response.status_code in {429, 500, 503},
            request_attempted=True,
            response_received=True,
        )
        if final_request and response.status_code >= 500:
            raise PublishUncertainError("FINAL_REQUEST_OUTCOME_UNCERTAIN", record)
        status_map = {
            400: "LINKEDIN_VALIDATION_ERROR",
            401: "LINKEDIN_AUTH_REQUIRED",
            403: "LINKEDIN_PERMISSION_DENIED",
            404: "LINKEDIN_RESOURCE_NOT_FOUND",
            409: "LINKEDIN_CONFLICT",
            426: "LINKEDIN_VERSION_UNSUPPORTED",
            429: "LINKEDIN_RATE_LIMITED",
            500: "LINKEDIN_SERVER_ERROR",
            503: "LINKEDIN_UNAVAILABLE",
        }
        prefix = "FINAL_" if final_request else ""
        safe_code = prefix + status_map.get(response.status_code, "LINKEDIN_HTTP_ERROR")
        raise LinkedInError(safe_code, record)
