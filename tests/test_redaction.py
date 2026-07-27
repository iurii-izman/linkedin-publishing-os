from __future__ import annotations

from publisher_api.redaction import REDACTED, redact, redact_text


def test_redacts_tokens_headers_and_upload_query() -> None:
    value = {
        "Authorization": "Bearer AQ-synthetic-secret-token-value",
        "access_token": "AQ-another-secret-token-value",
        "upload_url": "https://www.linkedin.com/dms-uploads/file?secret=query",
    }
    result = redact(value)
    rendered = repr(result)
    assert "synthetic-secret" not in rendered
    assert "secret=query" not in rendered
    assert rendered.count(REDACTED) >= 3


def test_redacts_tokenish_value_inside_log_message() -> None:
    message = "failure for Bearer AQ-synthetic-secret-token-value"
    assert "synthetic-secret" not in redact_text(message)


def test_redacts_embedded_signed_upload_url_and_secret_assignments() -> None:
    message = (
        "upload failed at https://www.linkedin.com/dms-uploads/opaque/file?"
        "signature=sensitive client_secret=sensitive-value"
    )
    sanitized = redact_text(message)
    assert "dms-uploads" not in sanitized
    assert "signature=" not in sanitized
    assert "sensitive-value" not in sanitized


def test_redacts_linkedin_resource_urns_from_messages() -> None:
    sanitized = redact_text("owner urn:li:person:member_123 image urn:li:image:opaque_123")
    assert "urn:li:person:" not in sanitized
    assert "urn:li:image:" not in sanitized
