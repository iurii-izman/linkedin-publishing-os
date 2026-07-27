from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

import httpx
import pytest

from publisher_api.cli import _safe_cli_error
from publisher_api.linkedin import (
    LinkedInClient,
    LinkedInError,
    LinkedInRequestStage,
)

TOKEN = "AQ-synthetic-secret-token-value"
AUTHOR = "urn:li:person:member_123"
IMAGE_URN = "urn:li:image:synthetic_123"
POST_URN = "urn:li:share:123456789"
IMAGE_BYTES = b"offline-png-bytes"
SIGNED_UPLOAD_URL = (
    "https://www.linkedin.com/dms-uploads/synthetic-image/uploaded-image/0?"
    "signature=offline-fixture"
)


@dataclass(frozen=True)
class SafeRequestObservation:
    stage: LinkedInRequestStage
    method: str
    host: str
    path: str
    query_parameters: dict[str, str]
    header_names: tuple[str, ...]
    content_type: str | None
    authorization_present: bool
    json_shape: dict[str, tuple[str, ...]] | None
    initialize_owner_is_person: bool
    byte_count: int
    status_resource_encoded: bool


class SafeRecordingTransport:
    def __init__(self, *, fail_stage: LinkedInRequestStage | None = None) -> None:
        self.fail_stage = fail_stage
        self.observations: list[SafeRequestObservation] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        stage = self._stage(request)
        self.observations.append(self._observe(request, stage))
        if stage == self.fail_stage:
            return httpx.Response(
                400,
                json={
                    "serviceErrorCode": 100,
                    "code": "INVALID_URN_ID",
                    "message": (
                        f"Rejected Bearer {TOKEN} for {SIGNED_UPLOAD_URL} "
                        "client_secret=offline-secret"
                    ),
                },
            )
        if stage == LinkedInRequestStage.INITIALIZE_UPLOAD:
            return httpx.Response(
                200,
                json={
                    "value": {
                        "image": IMAGE_URN,
                        "uploadUrl": SIGNED_UPLOAD_URL,
                        "uploadUrlExpiresAt": 1_800_000_000_000,
                    }
                },
            )
        if stage == LinkedInRequestStage.BINARY_UPLOAD:
            return httpx.Response(201)
        if stage == LinkedInRequestStage.IMAGE_STATUS:
            return httpx.Response(200, json={"id": IMAGE_URN, "status": "AVAILABLE"})
        return httpx.Response(201, headers={"x-restli-id": POST_URN})

    @staticmethod
    def _stage(request: httpx.Request) -> LinkedInRequestStage:
        if request.method == "POST" and request.url.path == "/rest/images":
            return LinkedInRequestStage.INITIALIZE_UPLOAD
        if request.url.host == "www.linkedin.com":
            return LinkedInRequestStage.BINARY_UPLOAD
        if request.method == "GET" and request.url.path.startswith("/rest/images/"):
            return LinkedInRequestStage.IMAGE_STATUS
        if request.method == "POST" and request.url.path == "/rest/posts":
            return LinkedInRequestStage.FINAL_POST
        raise AssertionError("unexpected offline request")

    @staticmethod
    def _observe(request: httpx.Request, stage: LinkedInRequestStage) -> SafeRequestObservation:
        query_parameters = (
            {key: value for key, value in request.url.params.multi_items()}
            if request.url.host != "www.linkedin.com"
            else {}
        )
        json_shape: dict[str, tuple[str, ...]] | None = None
        initialize_owner_is_person = False
        if request.headers.get("content-type") == "application/json" and request.content:
            payload = json.loads(request.content)
            json_shape = {"root": tuple(sorted(payload))}
            initialize = payload.get("initializeUploadRequest")
            if isinstance(initialize, dict):
                json_shape["initializeUploadRequest"] = tuple(sorted(initialize))
                owner = initialize.get("owner")
                initialize_owner_is_person = isinstance(owner, str) and owner.startswith(
                    "urn:li:person:"
                )
        return SafeRequestObservation(
            stage=stage,
            method=request.method,
            host=request.url.host,
            path=request.url.path,
            query_parameters=query_parameters,
            header_names=tuple(sorted(request.headers.keys())),
            content_type=request.headers.get("content-type"),
            authorization_present="authorization" in request.headers,
            json_shape=json_shape,
            initialize_owner_is_person=initialize_owner_is_person,
            byte_count=len(request.content),
            status_resource_encoded=b"urn%3Ali%3Aimage%3A" in request.url.raw_path,
        )


async def _offline_image_flow(
    settings: Any,
    recorder: SafeRecordingTransport,
) -> str:
    async with httpx.AsyncClient(
        base_url=str(settings.linkedin_api_base_url),
        transport=httpx.MockTransport(recorder.handler),
    ) as http_client:
        client = LinkedInClient(settings, http_client)
        reservation = await client.initialize_image(TOKEN, AUTHOR)
        await client.upload_image_once_and_wait(
            TOKEN,
            reservation,
            IMAGE_BYTES,
            "image/png",
        )
        receipt = await client.create_image_post(
            TOKEN,
            AUTHOR,
            "Offline synthetic caption",
            reservation.image_urn,
            "Offline synthetic alt text",
        )
    return receipt.post_urn


@pytest.mark.asyncio
async def test_offline_image_happy_path_captures_safe_contract(
    settings_factory: Any,
) -> None:
    settings = settings_factory(linkedin_api_base_url="https://api.linkedin.com")
    recorder = SafeRecordingTransport()
    assert await _offline_image_flow(settings, recorder) == POST_URN
    assert [observation.stage for observation in recorder.observations] == [
        LinkedInRequestStage.INITIALIZE_UPLOAD,
        LinkedInRequestStage.BINARY_UPLOAD,
        LinkedInRequestStage.IMAGE_STATUS,
        LinkedInRequestStage.FINAL_POST,
    ]

    initialize, upload, status, final = recorder.observations
    assert initialize.method == "POST"
    assert initialize.host == "api.linkedin.com"
    assert initialize.path == "/rest/images"
    assert initialize.query_parameters == {"action": "initializeUpload"}
    assert initialize.content_type == "application/json"
    assert initialize.authorization_present is True
    assert initialize.json_shape == {
        "root": ("initializeUploadRequest",),
        "initializeUploadRequest": ("owner",),
    }
    assert initialize.initialize_owner_is_person is True
    assert re.fullmatch(r"\d{6}", settings.linkedin_api_version)
    assert "linkedin-version" in initialize.header_names
    assert "x-restli-protocol-version" in initialize.header_names

    assert upload.method == "PUT"
    assert upload.host == "www.linkedin.com"
    assert upload.query_parameters == {}
    assert upload.authorization_present is True
    assert upload.content_type == "image/png"
    assert upload.byte_count == len(IMAGE_BYTES)
    assert upload.json_shape is None
    assert "linkedin-version" not in upload.header_names
    assert "x-restli-protocol-version" not in upload.header_names

    assert status.method == "GET"
    assert status.status_resource_encoded is True
    assert "linkedin-version" in status.header_names
    assert "x-restli-protocol-version" in status.header_names
    assert final.method == "POST"


@pytest.mark.parametrize(
    ("failed_stage", "expected_stages"),
    [
        (
            LinkedInRequestStage.INITIALIZE_UPLOAD,
            [LinkedInRequestStage.INITIALIZE_UPLOAD],
        ),
        (
            LinkedInRequestStage.BINARY_UPLOAD,
            [
                LinkedInRequestStage.INITIALIZE_UPLOAD,
                LinkedInRequestStage.BINARY_UPLOAD,
            ],
        ),
        (
            LinkedInRequestStage.IMAGE_STATUS,
            [
                LinkedInRequestStage.INITIALIZE_UPLOAD,
                LinkedInRequestStage.BINARY_UPLOAD,
                LinkedInRequestStage.IMAGE_STATUS,
            ],
        ),
    ],
)
@pytest.mark.asyncio
async def test_media_http_400_preserves_stage_stops_flow_and_never_retries(
    settings_factory: Any,
    failed_stage: LinkedInRequestStage,
    expected_stages: list[LinkedInRequestStage],
) -> None:
    settings = settings_factory(linkedin_api_base_url="https://api.linkedin.com")
    recorder = SafeRecordingTransport(fail_stage=failed_stage)
    with pytest.raises(LinkedInError) as exc_info:
        await _offline_image_flow(settings, recorder)
    error = exc_info.value
    assert error.safe_code == "LINKEDIN_VALIDATION_ERROR"
    assert error.record.stage == failed_stage
    assert error.record.http_status == 400
    assert error.record.error_category == "VALIDATION"
    assert error.record.service_error_code == 100
    assert error.record.linkedin_error_code == "INVALID_URN_ID"
    assert error.record.retryable is False
    assert error.record.request_attempted is True
    assert error.record.response_received is True
    assert error.record.sanitized_message is not None
    assert TOKEN not in error.record.sanitized_message
    assert SIGNED_UPLOAD_URL not in error.record.sanitized_message
    assert "signature=offline-fixture" not in error.record.sanitized_message
    assert [observation.stage for observation in recorder.observations] == expected_stages
    assert LinkedInRequestStage.FINAL_POST not in expected_stages
    assert expected_stages.count(failed_stage) == 1

    cli_error = _safe_cli_error(error)
    rendered = json.dumps(cli_error)
    assert cli_error["error"]["stage"] == failed_stage  # type: ignore[index]
    assert TOKEN not in rendered
    assert SIGNED_UPLOAD_URL not in rendered


@pytest.mark.asyncio
async def test_initialize_success_with_invalid_response_is_not_mapped_to_http_400(
    settings_factory: Any,
) -> None:
    settings = settings_factory(linkedin_api_base_url="https://api.linkedin.com")
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, json={"value": {}}))
    async with httpx.AsyncClient(
        base_url=str(settings.linkedin_api_base_url),
        transport=transport,
    ) as http_client:
        with pytest.raises(LinkedInError) as exc_info:
            await LinkedInClient(settings, http_client).initialize_image(TOKEN, AUTHOR)
    error = exc_info.value
    assert error.safe_code == "IMAGE_INITIALIZE_MALFORMED_RESPONSE"
    assert error.record.stage == LinkedInRequestStage.INITIALIZE_UPLOAD
    assert error.record.http_status == 200
    assert error.record.error_category == "MALFORMED_RESPONSE"
