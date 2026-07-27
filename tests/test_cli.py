from __future__ import annotations

from pathlib import Path

import pytest

from publisher_api.cli import DEFAULT_TEXT, _validate_stage0_text, main
from publisher_api.stage0_image import STAGE0_IMAGE_ALT_TEXT

OWNER_APPROVED_TEXT = (
    "Automation is not only about sending an API request.\n\n"
    "The more important question is: what should the system do when it cannot confirm "
    "whether the request succeeded?\n\n"
    "While building a small LinkedIn publishing prototype, I focused on this exact case. "
    "A timeout after the final request does not necessarily mean failure. Repeating it "
    "blindly may create a duplicate post.\n\n"
    "So the workflow uses a safer rule:\n\n"
    "• official OAuth and LinkedIn API only;\n"
    "• encrypted token storage;\n"
    "• human approval before publication;\n"
    "• exact content fingerprinting;\n"
    "• no automatic retry after an uncertain publishing result.\n\n"
    "This is also how I approach CRM and integration projects: first define states, "
    "exceptions and recovery rules, then automate the happy path.\n\n"
    "The first end-to-end text publishing flow is now ready. Next steps are media "
    "handling, scheduling and approval orchestration.\n\n"
    "Tech used: FastAPI, Python, OAuth 2.0 and the LinkedIn API.\n\n"
    "#SystemAnalysis #APIIntegration #Automation #Python"
)


@pytest.mark.parametrize("command", ["publish-text", "publish-image"])
def test_live_commands_require_explicit_confirmation(
    command: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("APP_PUBLIC_URL", "https://stage0.example.test")
    monkeypatch.setenv("LINKEDIN_CLIENT_ID", "synthetic-client-id")
    monkeypatch.setenv("LINKEDIN_CLIENT_SECRET", "synthetic-client-secret")
    monkeypatch.setenv(
        "LINKEDIN_REDIRECT_URI",
        "https://stage0.example.test/v1/oauth/linkedin/callback",
    )
    monkeypatch.setenv("LINKEDIN_API_VERSION", "202607")
    monkeypatch.setenv(
        "TOKEN_ENCRYPTION_KEY", "UG1lMFRoTE1MQm8xT3pVck5SWHdVdW1KSzVIM2NsQ3pVcXhzRQ=="
    )
    args = [command, "--text", DEFAULT_TEXT]
    if command == "publish-image":
        image = tmp_path / "synthetic.png"
        image.write_bytes(b"synthetic")
        args.extend(["--image", str(image), "--alt-text", STAGE0_IMAGE_ALT_TEXT])
    with pytest.raises(SystemExit, match="Refusing live publication"):
        main(args)


def test_live_text_has_no_implicit_synthetic_default() -> None:
    with pytest.raises(SystemExit):
        main(["publish-text", "--confirm-live-publish"])


def test_non_synthetic_live_text_is_rejected() -> None:
    with pytest.raises(SystemExit, match="exact owner-approved"):
        main(["publish-text", "--text", "ordinary text", "--confirm-live-publish"])


def test_exact_owner_approved_text_is_accepted() -> None:
    _validate_stage0_text(OWNER_APPROVED_TEXT)


@pytest.mark.parametrize(
    "mutated_text",
    [
        OWNER_APPROVED_TEXT.replace("Automation", "automation", 1),
        OWNER_APPROVED_TEXT.replace("Automation is", "Automation  is", 1),
        OWNER_APPROVED_TEXT.replace("\n\n", "\n", 1),
        OWNER_APPROVED_TEXT + "x",
        OWNER_APPROVED_TEXT[:-1],
        "arbitrary non-synthetic text",
    ],
    ids=[
        "one-character",
        "one-space",
        "one-newline",
        "added-text",
        "deleted-text",
        "arbitrary-text",
    ],
)
def test_owner_approved_text_mutations_are_rejected(mutated_text: str) -> None:
    with pytest.raises(SystemExit, match="exact owner-approved"):
        _validate_stage0_text(mutated_text)


def test_existing_synthetic_guard_still_accepts_synthetic_fixture() -> None:
    _validate_stage0_text(DEFAULT_TEXT)
