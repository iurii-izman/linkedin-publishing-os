from __future__ import annotations

import argparse
import asyncio
import hashlib
import hmac
import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import NoReturn

import httpx

from publisher_api.linkedin import LinkedInClient, LinkedInError
from publisher_api.oauth import OAuthClient, OAuthTokenVerificationError
from publisher_api.redaction import redact
from publisher_api.settings import Settings
from publisher_api.stage0_image import (
    STAGE0_IMAGE_ALT_TEXT,
    Stage0ImageApprovalError,
    Stage0ImageReview,
    Stage0ImageValidationError,
    build_stage0_image_review,
    image_review_is_live_approved,
    save_stage0_image_review,
    validate_stage0_png,
)
from publisher_api.token_store import EncryptedConnectionStore, StoredConnection

SYNTHETIC_PREFIX = "[SYNTHETIC STAGE 0]"
REQUIRED_STAGE0_SCOPES = {"openid", "profile", "w_member_social"}
DEFAULT_TEXT = (
    "[SYNTHETIC STAGE 0] Official LinkedIn API feasibility check. "
    "This temporary post contains no client or employer data."
)
OWNER_APPROVED_TEXT_HASHES = frozenset(
    {"55f704bdbc6dfa4cdb0ebfd5d737690a0c2329b26ae35408e8f9ff35eea34134"}
)
MEDIA_UNCERTAIN_CODES = frozenset(
    {
        "IMAGE_INITIALIZE_NETWORK_ERROR",
        "IMAGE_INITIALIZE_MALFORMED_RESPONSE",
        "IMAGE_UPLOAD_NETWORK_ERROR",
        "IMAGE_STATUS_NETWORK_ERROR",
        "IMAGE_STATUS_MALFORMED_RESPONSE",
        "IMAGE_STATUS_UNKNOWN",
        "IMAGE_PROCESSING_TIMEOUT",
    }
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Controlled Stage 0 LinkedIn smoke harness")
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare_text = subparsers.add_parser("prepare-text")
    prepare_text.add_argument("--author-urn", required=True)
    prepare_text.add_argument("--text", default=DEFAULT_TEXT)

    publish_text = subparsers.add_parser("publish-text")
    publish_text.add_argument("--text", required=True)
    publish_text.add_argument("--confirm-live-publish", action="store_true")

    prepare_image = subparsers.add_parser("prepare-image")
    prepare_image.add_argument("--image", type=Path, required=True)
    prepare_image.add_argument("--text", required=True)
    prepare_image.add_argument("--alt-text", required=True)

    publish_image = subparsers.add_parser("publish-image")
    publish_image.add_argument("--image", type=Path, required=True)
    publish_image.add_argument("--text", required=True)
    publish_image.add_argument("--alt-text", required=True)
    publish_image.add_argument("--confirm-live-publish", action="store_true")
    return parser


def _reject(message: str, code: int = 2) -> NoReturn:
    raise SystemExit(f"{message} (exit {code})")


def stage0_text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _validate_stage0_text(text: str, *, allow_owner_approved_hash: bool = True) -> None:
    if text.startswith(SYNTHETIC_PREFIX):
        return
    text_hash = stage0_text_hash(text)
    if allow_owner_approved_hash and any(
        hmac.compare_digest(text_hash, allowed) for allowed in OWNER_APPROVED_TEXT_HASHES
    ):
        return
    _reject("Live smoke text is neither synthetic nor an exact owner-approved content hash")


def _validate_image(path: Path) -> tuple[bytes, str]:
    try:
        validated = validate_stage0_png(path)
    except Stage0ImageValidationError as exc:
        _reject(str(exc))
    return path.read_bytes(), validated.mime_type


def _settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


def _client(settings: Settings, http_client: httpx.AsyncClient) -> LinkedInClient:
    return LinkedInClient(settings, http_client)


def _timeout(settings: Settings) -> httpx.Timeout:
    return httpx.Timeout(
        connect=settings.linkedin_timeout_connect_seconds,
        read=settings.linkedin_timeout_read_seconds,
        write=settings.linkedin_timeout_read_seconds,
        pool=settings.linkedin_timeout_connect_seconds,
    )


async def _prepare_text_plan(settings: Settings, author_urn: str, text: str) -> dict[str, object]:
    async with httpx.AsyncClient(timeout=_timeout(settings)) as http_client:
        request = _client(settings, http_client).prepare_text(author_urn, text)
    return asdict(request)


async def _prepare_image_plan(settings: Settings, author_urn: str) -> dict[str, object]:
    async with httpx.AsyncClient(timeout=_timeout(settings)) as http_client:
        request = _client(settings, http_client).prepare_image_initialize(author_urn)
    return asdict(request)


def _validate_connection(settings: Settings, connection: StoredConnection) -> None:
    if connection.expires_at <= datetime.now(UTC):
        _reject("Encrypted LinkedIn connection is expired; complete OAuth again", code=1)
    if not REQUIRED_STAGE0_SCOPES.issubset(set(connection.granted_scopes)):
        _reject("Encrypted LinkedIn connection lacks required Stage 0 scopes", code=1)
    if connection.api_version != settings.linkedin_api_version:
        _reject("Connection API version differs from current configuration", code=1)


def _safe_cli_error(exc: LinkedInError) -> dict[str, object]:
    if exc.safe_code == "MEDIA_UPLOAD_UNCERTAIN" or exc.safe_code in MEDIA_UNCERTAIN_CODES:
        outcome = "MEDIA_UPLOAD_UNCERTAIN"
    elif exc.safe_code in {
        "FINAL_REQUEST_OUTCOME_UNCERTAIN",
        "POST_CREATED_ID_MISSING",
    }:
        outcome = "PUBLISH_UNCERTAIN"
    else:
        outcome = "FAILED"
    return {
        "outcome": outcome,
        "safe_error_code": exc.safe_code,
        "http_status": exc.status_code,
        "error": asdict(exc.record),
    }


async def _verify_connection_introspection(
    settings: Settings, connection: StoredConnection
) -> None:
    try:
        async with httpx.AsyncClient(timeout=_timeout(settings)) as http_client:
            verified = await OAuthClient(settings, http_client).verify_introspection(
                connection.access_token
            )
    except (httpx.HTTPError, OAuthTokenVerificationError, ValueError):
        _reject("Stored LinkedIn token failed live introspection", code=1)
    if not REQUIRED_STAGE0_SCOPES.issubset(set(verified.granted_scopes)):
        _reject("Live token introspection lacks required Stage 0 scopes", code=1)


def _image_review(image: Path, text: str, alt_text: str) -> tuple[bytes, str, Stage0ImageReview]:
    try:
        validated = validate_stage0_png(image)
        review = build_stage0_image_review(
            repository_root=Path(__file__).resolve().parents[2],
            image=validated,
            caption=text,
            alt_text=alt_text,
        )
    except (Stage0ImageValidationError, Stage0ImageApprovalError) as exc:
        _reject(str(exc))
    return image.read_bytes(), validated.mime_type, review


async def _prepare_image_dry_run(
    settings: Settings, image: Path, text: str, alt_text: str
) -> dict[str, object]:
    connection = EncryptedConnectionStore(
        settings.stage0_token_store_path, settings.token_encryption_key
    ).load()
    _validate_connection(settings, connection)
    _, _, review = _image_review(image, text, alt_text)
    initialize_plan = await _prepare_image_plan(settings, connection.author_urn)
    if (
        initialize_plan.get("method") != "POST"
        or initialize_plan.get("path") != "/rest/images?action=initializeUpload"
    ):
        _reject("Unexpected Stage 0 image initialization plan")
    review_path = settings.stage0_token_store_path.parent / "image-review.json"
    save_stage0_image_review(review_path, review)
    return {
        "outcome": "IMAGE_DRY_RUN_READY",
        "identity": {
            "author_urn_present": True,
            "token_valid": True,
            "required_scopes_verified": True,
        },
        "image": {
            "path": review.image_path,
            "mime_type": review.mime_type,
            "width": review.width,
            "height": review.height,
            "mode": review.mode,
            "size_bytes": review.size_bytes,
            "checksum_created": True,
        },
        "caption": {
            "character_count": len(text),
            "hash_created": True,
        },
        "approval": {
            "fingerprint_created": True,
            "exact_caption_bound": True,
            "exact_image_bound": True,
            "live_approved": image_review_is_live_approved(review),
        },
        "future_requests": {
            "initialize_upload": "NOT_CALLED",
            "file_upload": "NOT_CALLED",
            "image_status_polling": "NOT_CALLED",
            "post_creation": "NOT_CALLED",
            "initialize_path": "/rest/images?action=initializeUpload",
            "post_path": "/rest/posts",
        },
        "alt_text": STAGE0_IMAGE_ALT_TEXT,
    }


async def _publish_text(settings: Settings, text: str) -> dict[str, object]:
    connection = EncryptedConnectionStore(
        settings.stage0_token_store_path, settings.token_encryption_key
    ).load()
    _validate_connection(settings, connection)
    await _verify_connection_introspection(settings, connection)
    async with httpx.AsyncClient(
        base_url=str(settings.linkedin_api_base_url), timeout=_timeout(settings)
    ) as http_client:
        receipt = await _client(settings, http_client).create_text_post(
            connection.access_token.get_secret_value(), connection.author_urn, text
        )
    return {"outcome": "PUBLISHED", "post_urn": receipt.post_urn, "http_status": 201}


async def _publish_image(
    settings: Settings, image: Path, text: str, alt_text: str
) -> dict[str, object]:
    data, content_type, review = _image_review(image, text, alt_text)
    if not image_review_is_live_approved(review):
        _reject("Image pair has not received explicit owner approval for live publication")
    connection = EncryptedConnectionStore(
        settings.stage0_token_store_path, settings.token_encryption_key
    ).load()
    _validate_connection(settings, connection)
    await _verify_connection_introspection(settings, connection)
    async with httpx.AsyncClient(
        base_url=str(settings.linkedin_api_base_url), timeout=_timeout(settings)
    ) as http_client:
        client = _client(settings, http_client)
        reservation = await client.initialize_image(
            connection.access_token.get_secret_value(), connection.author_urn
        )
        await client.upload_image_once_and_wait(
            connection.access_token.get_secret_value(),
            reservation,
            data,
            content_type,
        )
        receipt = await client.create_image_post(
            connection.access_token.get_secret_value(),
            connection.author_urn,
            text,
            reservation.image_urn,
            alt_text,
        )
    return {
        "outcome": "PUBLISHED",
        "post_urn": receipt.post_urn,
        "image_urn": reservation.image_urn,
        "http_status": 201,
    }


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)

    if args.command in {"publish-text", "publish-image"} and not args.confirm_live_publish:
        _reject("Refusing live publication without --confirm-live-publish")

    if args.command in {"prepare-text", "publish-text"}:
        _validate_stage0_text(
            args.text,
            allow_owner_approved_hash=True,
        )

    settings = _settings()
    if args.command == "prepare-text":
        request = asyncio.run(_prepare_text_plan(settings, args.author_urn, args.text))
        print(json.dumps(redact(request), indent=2, sort_keys=True))
        return 0

    if args.command == "prepare-image":
        prepare_result = asyncio.run(
            _prepare_image_dry_run(settings, args.image, args.text, args.alt_text)
        )
        print(json.dumps(redact(prepare_result), indent=2, sort_keys=True))
        return 0

    try:
        if args.command == "publish-text":
            live_result = asyncio.run(_publish_text(settings, args.text))
        else:
            live_result = asyncio.run(
                _publish_image(settings, args.image, args.text, args.alt_text)
            )
    except LinkedInError as exc:
        print(json.dumps(_safe_cli_error(exc), sort_keys=True))
        return 1
    print(json.dumps(redact(live_result), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
