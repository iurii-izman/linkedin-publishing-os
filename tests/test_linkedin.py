from __future__ import annotations

import httpx
import pytest

from publisher_api.linkedin import (
    ImageReservation,
    LinkedInClient,
    LinkedInError,
    PublishUncertainError,
    SafePreSendError,
    author_urn_from_subject,
)

TOKEN = "AQ-synthetic-secret-token-value"
AUTHOR = "urn:li:person:member_123"
POST_URN = "urn:li:share:123456789"
IMAGE_URN = "urn:li:image:synthetic_123"


def test_author_urn_construction() -> None:
    assert author_urn_from_subject("member_123") == AUTHOR
    with pytest.raises(ValueError):
        author_urn_from_subject("bad:subject")


@pytest.mark.asyncio
async def test_text_post_request_path_headers_payload_and_receipt(
    settings_factory: object,
) -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(201, headers={"x-restli-id": POST_URN})

    settings = settings_factory()  # type: ignore[operator]
    async with httpx.AsyncClient(
        base_url=str(settings.linkedin_api_base_url),
        transport=httpx.MockTransport(handler),
    ) as http_client:
        receipt = await LinkedInClient(settings, http_client).create_text_post(
            TOKEN, AUTHOR, "[SYNTHETIC STAGE 0] Test"
        )
    request = captured[0]
    assert request.method == "POST"
    assert request.url.path == "/rest/posts"
    assert request.headers["linkedin-version"] == "202607"
    assert request.headers["x-restli-protocol-version"] == "2.0.0"
    assert request.headers["authorization"] == f"Bearer {TOKEN}"
    assert b'"author":"urn:li:person:member_123"' in request.content
    assert b'"feedDistribution":"MAIN_FEED"' in request.content
    assert receipt.post_urn == POST_URN


@pytest.mark.asyncio
async def test_missing_x_restli_id_is_uncertain(settings_factory: object) -> None:
    settings = settings_factory()  # type: ignore[operator]
    transport = httpx.MockTransport(lambda _request: httpx.Response(201))
    async with httpx.AsyncClient(
        base_url=str(settings.linkedin_api_base_url), transport=transport
    ) as http_client:
        with pytest.raises(PublishUncertainError, match="POST_CREATED_ID_MISSING"):
            await LinkedInClient(settings, http_client).create_text_post(
                TOKEN, AUTHOR, "[SYNTHETIC STAGE 0] Test"
            )


@pytest.mark.parametrize(
    ("status", "safe_code"),
    [
        (400, "FINAL_LINKEDIN_VALIDATION_ERROR"),
        (401, "FINAL_LINKEDIN_AUTH_REQUIRED"),
        (403, "FINAL_LINKEDIN_PERMISSION_DENIED"),
        (409, "FINAL_LINKEDIN_CONFLICT"),
        (426, "FINAL_LINKEDIN_VERSION_UNSUPPORTED"),
        (429, "FINAL_LINKEDIN_RATE_LIMITED"),
        (500, "FINAL_LINKEDIN_SERVER_ERROR"),
        (503, "FINAL_LINKEDIN_UNAVAILABLE"),
    ],
)
@pytest.mark.asyncio
async def test_final_post_error_mapping(
    settings_factory: object, status: int, safe_code: str
) -> None:
    settings = settings_factory()  # type: ignore[operator]
    transport = httpx.MockTransport(lambda _request: httpx.Response(status))
    async with httpx.AsyncClient(
        base_url=str(settings.linkedin_api_base_url), transport=transport
    ) as http_client:
        with pytest.raises(LinkedInError) as exc_info:
            await LinkedInClient(settings, http_client).create_text_post(
                TOKEN, AUTHOR, "[SYNTHETIC STAGE 0] Test"
            )
    assert exc_info.value.safe_code == safe_code
    assert TOKEN not in repr(exc_info.value)


@pytest.mark.asyncio
async def test_timeout_before_send_is_safe(settings_factory: object) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("synthetic", request=request)

    settings = settings_factory()  # type: ignore[operator]
    async with httpx.AsyncClient(
        base_url=str(settings.linkedin_api_base_url),
        transport=httpx.MockTransport(handler),
    ) as http_client:
        with pytest.raises(SafePreSendError):
            await LinkedInClient(settings, http_client).create_text_post(
                TOKEN, AUTHOR, "[SYNTHETIC STAGE 0] Test"
            )


@pytest.mark.asyncio
async def test_timeout_after_final_request_begins_is_uncertain(settings_factory: object) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("synthetic", request=request)

    settings = settings_factory()  # type: ignore[operator]
    async with httpx.AsyncClient(
        base_url=str(settings.linkedin_api_base_url),
        transport=httpx.MockTransport(handler),
    ) as http_client:
        with pytest.raises(PublishUncertainError):
            await LinkedInClient(settings, http_client).create_text_post(
                TOKEN, AUTHOR, "[SYNTHETIC STAGE 0] Test"
            )


@pytest.mark.asyncio
async def test_image_initialize_upload_status_and_post(settings_factory: object) -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        if request.url.path == "/rest/images" and request.method == "POST":
            assert request.url.params["action"] == "initializeUpload"
            return httpx.Response(
                200,
                json={
                    "value": {
                        "image": IMAGE_URN,
                        "uploadUrl": (
                            "https://www.linkedin.com/dms-uploads/synthetic?"
                            "signature=redacted-by-harness"
                        ),
                        "uploadUrlExpiresAt": 1_800_000_000_000,
                    }
                },
            )
        if request.url.host == "www.linkedin.com":
            return httpx.Response(201)
        if request.url.path.startswith("/rest/images/"):
            return httpx.Response(200, json={"id": IMAGE_URN, "status": "AVAILABLE"})
        return httpx.Response(201, headers={"x-restli-id": POST_URN})

    settings = settings_factory()  # type: ignore[operator]
    async with httpx.AsyncClient(
        base_url=str(settings.linkedin_api_base_url),
        transport=httpx.MockTransport(handler),
    ) as http_client:
        client = LinkedInClient(settings, http_client)
        reservation = await client.initialize_image(TOKEN, AUTHOR)
        await client.upload_image(TOKEN, reservation, b"synthetic-image", "image/png")
        await client.wait_for_image(TOKEN, reservation.image_urn)
        receipt = await client.create_image_post(
            TOKEN,
            AUTHOR,
            "[SYNTHETIC STAGE 0] Image test",
            reservation.image_urn,
            "Synthetic image",
        )
    assert captured[0].url.path == "/rest/images"
    assert b'"owner":"urn:li:person:member_123"' in captured[0].content
    assert captured[1].method == "PUT"
    assert captured[1].headers["authorization"] == f"Bearer {TOKEN}"
    assert b'"altText":"Synthetic image"' in captured[-1].content
    assert receipt.post_urn == POST_URN


@pytest.mark.asyncio
async def test_untrusted_upload_url_is_rejected(settings_factory: object) -> None:
    settings = settings_factory()  # type: ignore[operator]
    reservation = ImageReservation(
        image_urn=IMAGE_URN,
        upload_url="https://attacker.example/dms-uploads/file?secret=value",
        upload_url_expires_at=1_800_000_000_000,
    )
    async with httpx.AsyncClient(
        base_url=str(settings.linkedin_api_base_url),
        transport=httpx.MockTransport(lambda _request: httpx.Response(500)),
    ) as http_client:
        with pytest.raises(LinkedInError, match="UNTRUSTED_UPLOAD_URL"):
            await LinkedInClient(settings, http_client).upload_image(
                TOKEN, reservation, b"data", "image/png"
            )
