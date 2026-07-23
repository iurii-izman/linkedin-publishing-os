from __future__ import annotations

from pathlib import Path

import pytest

from publisher_api.cli import DEFAULT_TEXT, main


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
        args.extend(["--image", str(image)])
    with pytest.raises(SystemExit, match="Refusing live publication"):
        main(args)


def test_non_synthetic_live_text_is_rejected() -> None:
    with pytest.raises(SystemExit, match="must start"):
        main(["publish-text", "--text", "ordinary text", "--confirm-live-publish"])
