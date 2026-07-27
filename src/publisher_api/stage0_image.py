from __future__ import annotations

import hashlib
import hmac
import json
import mimetypes
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

from PIL import Image, UnidentifiedImageError

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
STAGE0_IMAGE_DIMENSIONS = (1200, 1200)
STAGE0_IMAGE_MIME = "image/png"
STAGE0_IMAGE_MODE = "RGB"
STAGE0_IMAGE_MAX_BYTES = 10 * 1024 * 1024
STAGE0_IMAGE_ALT_TEXT = (
    "Architecture diagram of a human-approved LinkedIn publishing workflow "
    "with an explicit Publish Uncertain state."
)
STAGE0_IMAGE_CAPTION_SHA256 = "dd20ada65520c3fc524cea71caa1ad522642666edf7235518b02b475daa3d547"
STAGE0_IMAGE_CHECKSUM_SHA256 = "8f265637c8cd10911f49afa2040ee0dbd70c9732b9a0549c418cb79fae50de86"

# The one-time owner approval was consumed by the successful Stage 0 image flow.
# A new live attempt requires a new explicit owner checkpoint.
OWNER_APPROVED_IMAGE_FINGERPRINTS: frozenset[str] = frozenset()


class Stage0ImageValidationError(ValueError):
    pass


class Stage0ImageApprovalError(ValueError):
    pass


@dataclass(frozen=True)
class ValidatedStage0Image:
    path: Path
    checksum_sha256: str
    size_bytes: int
    width: int
    height: int
    format: str
    mode: str
    mime_type: str


@dataclass(frozen=True)
class Stage0ImageReview:
    version: int
    image_path: str
    image_checksum_sha256: str
    caption_sha256: str
    approval_fingerprint: str
    alt_text: str
    size_bytes: int
    width: int
    height: int
    format: str
    mode: str
    mime_type: str


def sha256_utf8(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def image_approval_fingerprint(caption_sha256: str, image_sha256: str) -> str:
    if len(caption_sha256) != 64 or len(image_sha256) != 64:
        raise ValueError("approval inputs must be SHA-256 hex digests")
    return sha256_utf8(f"{caption_sha256}:{image_sha256}")


def validate_stage0_png(path: Path) -> ValidatedStage0Image:
    if not path.is_file():
        raise Stage0ImageValidationError("Stage 0 image path is not a file")
    if path.suffix.lower() != ".png" or mimetypes.guess_type(path.name)[0] != STAGE0_IMAGE_MIME:
        raise Stage0ImageValidationError("Stage 0 image must use the PNG MIME type")

    data = path.read_bytes()
    if not data.startswith(PNG_SIGNATURE):
        raise Stage0ImageValidationError("Stage 0 image has an invalid PNG signature")
    if len(data) > STAGE0_IMAGE_MAX_BYTES:
        raise Stage0ImageValidationError("Stage 0 image exceeds the local size limit")

    try:
        with Image.open(path) as image:
            if image.format != "PNG":
                raise Stage0ImageValidationError("Stage 0 image format is not PNG")
            image.verify()
        with Image.open(path) as image:
            width, height = image.size
            mode = image.mode
    except (OSError, SyntaxError, UnidentifiedImageError) as exc:
        raise Stage0ImageValidationError("Stage 0 image is not a readable PNG") from exc

    if (width, height) != STAGE0_IMAGE_DIMENSIONS:
        raise Stage0ImageValidationError("Stage 0 image must be exactly 1200 x 1200")
    if mode != STAGE0_IMAGE_MODE:
        raise Stage0ImageValidationError("Stage 0 image must use RGB mode without transparency")

    return ValidatedStage0Image(
        path=path,
        checksum_sha256=sha256_bytes(data),
        size_bytes=len(data),
        width=width,
        height=height,
        format="PNG",
        mode=mode,
        mime_type=STAGE0_IMAGE_MIME,
    )


def build_stage0_image_review(
    *,
    repository_root: Path,
    image: ValidatedStage0Image,
    caption: str,
    alt_text: str,
) -> Stage0ImageReview:
    caption_sha256 = sha256_utf8(caption)
    if not hmac.compare_digest(caption_sha256, STAGE0_IMAGE_CAPTION_SHA256):
        raise Stage0ImageApprovalError("Image caption does not match the review allowlist")
    if not hmac.compare_digest(image.checksum_sha256, STAGE0_IMAGE_CHECKSUM_SHA256):
        raise Stage0ImageApprovalError("Image checksum does not match the review allowlist")
    if not hmac.compare_digest(alt_text, STAGE0_IMAGE_ALT_TEXT):
        raise Stage0ImageApprovalError("Image alt text does not match the review allowlist")
    try:
        relative_path = image.path.resolve().relative_to(repository_root.resolve()).as_posix()
    except ValueError as exc:
        raise Stage0ImageApprovalError("Stage 0 image must be inside the repository") from exc
    return Stage0ImageReview(
        version=1,
        image_path=relative_path,
        image_checksum_sha256=image.checksum_sha256,
        caption_sha256=caption_sha256,
        approval_fingerprint=image_approval_fingerprint(caption_sha256, image.checksum_sha256),
        alt_text=alt_text,
        size_bytes=image.size_bytes,
        width=image.width,
        height=image.height,
        format=image.format,
        mode=image.mode,
        mime_type=image.mime_type,
    )


def image_review_is_live_approved(review: Stage0ImageReview) -> bool:
    return any(
        hmac.compare_digest(review.approval_fingerprint, approved)
        for approved in OWNER_APPROVED_IMAGE_FINGERPRINTS
    )


def save_stage0_image_review(path: Path, review: Stage0ImageReview) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(asdict(review), indent=2, sort_keys=True).encode("utf-8")
    file_descriptor, temporary_name = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(file_descriptor, "wb") as stream:
            stream.write(serialized)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)
