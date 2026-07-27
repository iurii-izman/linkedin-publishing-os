from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from PIL import Image
from pydantic import SecretStr

from publisher_api.cli import OWNER_APPROVED_TEXT_HASHES, _prepare_image_dry_run
from publisher_api.settings import Settings
from publisher_api.stage0_image import (
    STAGE0_IMAGE_ALT_TEXT,
    STAGE0_IMAGE_CAPTION_SHA256,
    STAGE0_IMAGE_CHECKSUM_SHA256,
    Stage0ImageApprovalError,
    Stage0ImageValidationError,
    build_stage0_image_review,
    image_approval_fingerprint,
    image_review_is_live_approved,
    sha256_bytes,
    sha256_utf8,
    validate_stage0_png,
)
from publisher_api.token_store import EncryptedConnectionStore, StoredConnection

CAPTION = (
    "After validating the first text post through the official LinkedIn API, I mapped the "
    "workflow as a state machine rather than a linear script.\n\n"
    "The important states are not only Draft and Published. They also include Approved, "
    "Scheduled, Publishing, Failed and Publish Uncertain.\n\n"
    "The last state matters when the final API request times out. The system cannot safely "
    "assume failure and repeat the request: the post may already exist.\n\n"
    "The workflow therefore preserves the request evidence, blocks automatic retry and "
    "requires manual verification.\n\n"
    "The next version will add media handling, Telegram approval, scheduling and "
    "PostgreSQL-backed audit history.\n\n"
    "Architecture: FastAPI as the LinkedIn boundary, n8n for orchestration, PostgreSQL for "
    "state and human approval bound to the exact content hash.\n\n"
    "#SystemDesign #WorkflowAutomation #APIIntegration #FastAPI"
)
PROJECT_IMAGE = Path("assets/stage0/linkedin-publishing-workflow.png")


def _write_png(path: Path, *, size: tuple[int, int] = (1200, 1200), mode: str = "RGB") -> None:
    Image.new(mode, size, "navy").save(path, format="PNG")


def test_valid_stage0_png_is_accepted(tmp_path: Path) -> None:
    path = tmp_path / "valid.png"
    _write_png(path)
    validated = validate_stage0_png(path)
    assert (validated.width, validated.height) == (1200, 1200)
    assert validated.mode == "RGB"
    assert validated.mime_type == "image/png"


def test_wrong_dimensions_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "wrong.png"
    _write_png(path, size=(1200, 1199))
    with pytest.raises(Stage0ImageValidationError, match="1200 x 1200"):
        validate_stage0_png(path)


def test_unsupported_mime_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "wrong.jpg"
    _write_png(path)
    with pytest.raises(Stage0ImageValidationError, match="PNG MIME"):
        validate_stage0_png(path)


def test_corrupted_png_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "corrupt.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\ncorrupt")
    with pytest.raises(Stage0ImageValidationError, match="readable PNG"):
        validate_stage0_png(path)


def test_one_byte_change_changes_checksum(tmp_path: Path) -> None:
    path = tmp_path / "valid.png"
    _write_png(path)
    original = path.read_bytes()
    assert sha256_bytes(original) != sha256_bytes(original + b"\x00")


def test_one_character_change_changes_caption_hash() -> None:
    assert sha256_utf8(CAPTION) == STAGE0_IMAGE_CAPTION_SHA256
    assert sha256_utf8(CAPTION + "x") != STAGE0_IMAGE_CAPTION_SHA256


def test_approval_fingerprint_binds_caption_and_image() -> None:
    expected = image_approval_fingerprint(STAGE0_IMAGE_CAPTION_SHA256, STAGE0_IMAGE_CHECKSUM_SHA256)
    assert expected != image_approval_fingerprint(
        sha256_utf8(CAPTION + "x"), STAGE0_IMAGE_CHECKSUM_SHA256
    )
    assert expected != image_approval_fingerprint(
        STAGE0_IMAGE_CAPTION_SHA256, sha256_bytes(b"mutated image")
    )


def test_old_text_approval_cannot_approve_image() -> None:
    old_text_hash = next(iter(OWNER_APPROVED_TEXT_HASHES))
    assert old_text_hash != STAGE0_IMAGE_CAPTION_SHA256
    assert image_approval_fingerprint(
        old_text_hash, STAGE0_IMAGE_CHECKSUM_SHA256
    ) != image_approval_fingerprint(STAGE0_IMAGE_CAPTION_SHA256, STAGE0_IMAGE_CHECKSUM_SHA256)


def test_arbitrary_caption_or_image_is_rejected(tmp_path: Path) -> None:
    project_root = Path.cwd()
    validated = validate_stage0_png(PROJECT_IMAGE)
    with pytest.raises(Stage0ImageApprovalError, match="caption"):
        build_stage0_image_review(
            repository_root=project_root,
            image=validated,
            caption=CAPTION + "x",
            alt_text=STAGE0_IMAGE_ALT_TEXT,
        )

    arbitrary_path = project_root / "assets" / "stage0" / "arbitrary.png"
    try:
        _write_png(arbitrary_path)
        arbitrary = validate_stage0_png(arbitrary_path)
        with pytest.raises(Stage0ImageApprovalError, match="checksum"):
            build_stage0_image_review(
                repository_root=project_root,
                image=arbitrary,
                caption=CAPTION,
                alt_text=STAGE0_IMAGE_ALT_TEXT,
            )
    finally:
        arbitrary_path.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_prepare_image_dry_run_makes_no_linkedin_request(
    settings_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings: Settings = settings_factory()
    connection = StoredConnection(
        access_token=SecretStr("AQ-synthetic-secret-token-value"),
        expires_at=datetime.now(UTC) + timedelta(days=1),
        granted_scopes=["openid", "profile", "w_member_social"],
        member_subject="member_123",
        author_urn="urn:li:person:member_123",
        api_version="202607",
    )
    EncryptedConnectionStore(settings.stage0_token_store_path, settings.token_encryption_key).save(
        connection
    )
    request_attempted = False
    original_request = httpx.AsyncClient.request

    async def reject_request(self: httpx.AsyncClient, *args: object, **kwargs: object) -> Any:
        nonlocal request_attempted
        request_attempted = True
        raise AssertionError("dry-run attempted a network request")

    monkeypatch.setattr(httpx.AsyncClient, "request", reject_request)
    try:
        result = await _prepare_image_dry_run(
            settings, PROJECT_IMAGE, CAPTION, STAGE0_IMAGE_ALT_TEXT
        )
    finally:
        monkeypatch.setattr(httpx.AsyncClient, "request", original_request)
    assert request_attempted is False
    assert result["outcome"] == "IMAGE_DRY_RUN_READY"
    assert result["future_requests"] == {
        "initialize_upload": "NOT_CALLED",
        "file_upload": "NOT_CALLED",
        "image_status_polling": "NOT_CALLED",
        "post_creation": "NOT_CALLED",
        "initialize_path": "/rest/images?action=initializeUpload",
        "post_path": "/rest/posts",
    }
    approval = result["approval"]
    assert isinstance(approval, dict)
    assert approval["live_approved"] is False


def test_consumed_image_approval_cannot_start_another_live_flow() -> None:
    validated = validate_stage0_png(PROJECT_IMAGE)
    review = build_stage0_image_review(
        repository_root=Path.cwd(),
        image=validated,
        caption=CAPTION,
        alt_text=STAGE0_IMAGE_ALT_TEXT,
    )
    assert image_review_is_live_approved(review) is False
