from __future__ import annotations

import argparse
import asyncio
import json
import mimetypes
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import NoReturn

import httpx

from publisher_api.linkedin import LinkedInClient, LinkedInError
from publisher_api.redaction import redact
from publisher_api.settings import Settings
from publisher_api.token_store import EncryptedConnectionStore, StoredConnection

SYNTHETIC_PREFIX = "[SYNTHETIC STAGE 0]"
DEFAULT_TEXT = (
    "[SYNTHETIC STAGE 0] Official LinkedIn API feasibility check. "
    "This temporary post contains no client or employer data."
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Controlled Stage 0 LinkedIn smoke harness")
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare_text = subparsers.add_parser("prepare-text")
    prepare_text.add_argument("--author-urn", required=True)
    prepare_text.add_argument("--text", default=DEFAULT_TEXT)

    publish_text = subparsers.add_parser("publish-text")
    publish_text.add_argument("--text", default=DEFAULT_TEXT)
    publish_text.add_argument("--confirm-live-publish", action="store_true")

    prepare_image = subparsers.add_parser("prepare-image")
    prepare_image.add_argument("--author-urn", required=True)
    prepare_image.add_argument("--image", type=Path, required=True)
    prepare_image.add_argument("--text", default=DEFAULT_TEXT)
    prepare_image.add_argument("--alt-text", default="Synthetic Stage 0 test image")

    publish_image = subparsers.add_parser("publish-image")
    publish_image.add_argument("--image", type=Path, required=True)
    publish_image.add_argument("--text", default=DEFAULT_TEXT)
    publish_image.add_argument("--alt-text", default="Synthetic Stage 0 test image")
    publish_image.add_argument("--confirm-live-publish", action="store_true")
    return parser


def _reject(message: str, code: int = 2) -> NoReturn:
    raise SystemExit(f"{message} (exit {code})")


def _validate_synthetic_text(text: str) -> None:
    if not text.startswith(SYNTHETIC_PREFIX):
        _reject(f"Live smoke text must start with {SYNTHETIC_PREFIX!r}")


def _validate_image(path: Path) -> tuple[bytes, str]:
    if not path.is_file():
        _reject("Image path is not a file")
    content_type = mimetypes.guess_type(path.name)[0]
    if content_type not in {"image/jpeg", "image/png"}:
        _reject("Stage 0 image must be a JPEG or PNG")
    data = path.read_bytes()
    if not data:
        _reject("Stage 0 image must not be empty")
    return data, content_type


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
    if "w_member_social" not in connection.granted_scopes:
        _reject("Encrypted LinkedIn connection lacks w_member_social", code=1)
    if connection.api_version != settings.linkedin_api_version:
        _reject("Connection API version differs from current configuration", code=1)


async def _publish_text(settings: Settings, text: str) -> dict[str, object]:
    connection = EncryptedConnectionStore(
        settings.stage0_token_store_path, settings.token_encryption_key
    ).load()
    _validate_connection(settings, connection)
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
    data, content_type = _validate_image(image)
    connection = EncryptedConnectionStore(
        settings.stage0_token_store_path, settings.token_encryption_key
    ).load()
    _validate_connection(settings, connection)
    async with httpx.AsyncClient(
        base_url=str(settings.linkedin_api_base_url), timeout=_timeout(settings)
    ) as http_client:
        client = _client(settings, http_client)
        reservation = await client.initialize_image(
            connection.access_token.get_secret_value(), connection.author_urn
        )
        await client.upload_image(
            connection.access_token.get_secret_value(), reservation, data, content_type
        )
        await client.wait_for_image(
            connection.access_token.get_secret_value(), reservation.image_urn
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
    _validate_synthetic_text(args.text)

    if args.command in {"publish-text", "publish-image"} and not args.confirm_live_publish:
        _reject("Refusing live publication without --confirm-live-publish")

    settings = _settings()
    if args.command == "prepare-text":
        request = asyncio.run(_prepare_text_plan(settings, args.author_urn, args.text))
        print(json.dumps(redact(request), indent=2, sort_keys=True))
        return 0

    if args.command == "prepare-image":
        _validate_image(args.image)
        request = asyncio.run(_prepare_image_plan(settings, args.author_urn))
        prepare_result = {
            "initialize": request,
            "final_post_will_include": {
                "commentary": args.text,
                "alt_text": args.alt_text,
                "image_file": args.image.name,
            },
        }
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
        print(
            json.dumps(
                {
                    "outcome": "UNCERTAIN"
                    if exc.safe_code
                    in {"FINAL_REQUEST_OUTCOME_UNCERTAIN", "POST_CREATED_ID_MISSING"}
                    else "FAILED",
                    "safe_error_code": exc.safe_code,
                    "http_status": exc.status_code,
                },
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(redact(live_result), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
