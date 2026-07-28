from __future__ import annotations

import asyncio
import logging
import os
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy import Engine, create_engine, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from publisher_api.main import create_app
from publisher_api.settings import Settings
from publisher_api.stage1_cli import main as stage1_cli_main
from publisher_api.stage1_domain import (
    CANONICALIZATION_VERSION,
    DomainError,
    PublicationStatus,
    transition_publication,
    utc_text_sha256,
)
from publisher_api.stage1_models import (
    LinkedInConnection,
    PostRevision,
    PublicationAttempt,
)
from publisher_api.stage1_publisher import (
    FakeLinkedInPublisher,
    TextPostCommand,
    TextPostReceipt,
)
from publisher_api.stage1_services import AuditService
from publisher_api.token_store import EncryptedConnectionStore, StoredConnection

TEST_DATABASE_URL = os.getenv("STAGE1_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="STAGE1_TEST_DATABASE_URL is required for PostgreSQL integration tests",
)


@pytest.fixture(scope="session")
def stage1_engine() -> Iterator[Engine]:
    assert TEST_DATABASE_URL is not None
    engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    yield engine
    engine.dispose()


@pytest.fixture(autouse=True)
def clean_stage1_database(stage1_engine: Engine) -> Iterator[None]:
    table_names = [
        "publication_attempts",
        "idempotency_records",
        "publications",
        "approvals",
        "linkedin_connections",
        "audit_events",
        "drafts",
        "post_revisions",
    ]
    with stage1_engine.begin() as connection:
        connection.execute(
            text(f"TRUNCATE TABLE {', '.join(table_names)} RESTART IDENTITY CASCADE")
        )
    yield


def _stage1_settings(
    settings_factory: Callable[..., Settings],
    database_url: str,
    **overrides: object,
) -> Settings:
    values: dict[str, object] = {
        "database_url": database_url,
        "app_owner_key": "synthetic-stage1-owner-key-with-32-characters",
        "linkedin_publisher_mode": "fake-success",
    }
    values.update(overrides)
    return settings_factory(**values)


def _import_connection(
    app: FastAPI,
    settings: Settings,
    *,
    token: str = "AQ-synthetic-stage1-token-value",
) -> uuid.UUID:
    stored = StoredConnection(
        access_token=SecretStr(token),
        expires_at=datetime.now(UTC) + timedelta(days=1),
        granted_scopes=["openid", "profile", "w_member_social"],
        member_subject="member_stage1",
        author_urn="urn:li:person:member_stage1",
        api_version="202607",
    )
    EncryptedConnectionStore(settings.stage0_token_store_path, settings.token_encryption_key).save(
        stored
    )
    result = app.state.stage1_services.connections.import_stage0(confirm=True)
    replay = app.state.stage1_services.connections.import_stage0(confirm=True)
    assert replay["created"] is False
    return uuid.UUID(result["connection_id"])


async def _client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://stage1.example.test",
    ) as client:
        yield client


def _headers(settings: Settings, key: str) -> dict[str, str]:
    return {
        "X-Owner-Key": settings.owner_key.get_secret_value(),
        "Idempotency-Key": key,
    }


async def _prepared_flow(
    client: httpx.AsyncClient,
    settings: Settings,
    connection_id: uuid.UUID,
    *,
    prefix: str = "flow",
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    draft_response = await client.post(
        "/v1/drafts",
        json={"title": "Synthetic Stage 1 draft"},
        headers=_headers(settings, f"{prefix}-draft-key-0001"),
    )
    assert draft_response.status_code == 201
    draft = draft_response.json()
    revision_response = await client.post(
        f"/v1/drafts/{draft['id']}/revisions",
        json={"text": "Exact synthetic Stage 1 text.\n", "created_by": "owner"},
        headers=_headers(settings, f"{prefix}-revision-key-0001"),
    )
    assert revision_response.status_code == 201
    revision = revision_response.json()
    approval_response = await client.post(
        f"/v1/revisions/{revision['id']}/approve",
        json={"approved_by": "owner"},
        headers=_headers(settings, f"{prefix}-approval-key-0001"),
    )
    assert approval_response.status_code == 201
    approval = approval_response.json()
    publication_response = await client.post(
        "/v1/publications/prepare",
        json={
            "revision_id": revision["id"],
            "approval_id": approval["id"],
            "connection_id": str(connection_id),
        },
        headers=_headers(settings, f"{prefix}-prepare-key-0001"),
    )
    assert publication_response.status_code == 201
    return draft, revision, approval, publication_response.json()


def test_exact_hash_and_transition_guards() -> None:
    assert utc_text_sha256("a b") != utc_text_sha256("a  b")
    assert utc_text_sha256("a\nb") != utc_text_sha256("a\r\nb")
    assert CANONICALIZATION_VERSION == "utf8-exact-v1"
    assert (
        transition_publication(PublicationStatus.PREPARED, PublicationStatus.PUBLISHING)
        == PublicationStatus.PUBLISHING
    )
    with pytest.raises(DomainError, match="INVALID_PUBLICATION_TRANSITION"):
        transition_publication(PublicationStatus.PUBLISHED, PublicationStatus.PUBLISHING)


def test_stage1_cli_configuration_error_is_safe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invalid_secret = "invalid-sensitive-encryption-value"
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", invalid_secret)
    with pytest.raises(SystemExit) as captured:
        stage1_cli_main(["reconcile-stale-publications", "--dry-run"])
    message = str(captured.value)
    assert "CONFIGURATION_INVALID" in message
    assert invalid_secret not in message


@pytest.mark.asyncio
async def test_full_api_happy_path_idempotency_restart_and_encryption(
    settings_factory: Callable[..., Settings],
    stage1_engine: Engine,
    caplog: pytest.LogCaptureFixture,
) -> None:
    assert TEST_DATABASE_URL is not None
    settings = _stage1_settings(settings_factory, TEST_DATABASE_URL)
    publisher = FakeLinkedInPublisher()
    caplog.set_level(logging.INFO, logger="publisher_api.stage1")
    app = create_app(settings, stage1_engine=stage1_engine, stage1_publisher=publisher)
    connection_id = _import_connection(app, settings)
    token = "AQ-synthetic-stage1-token-value"

    async for client in _client(app):
        draft, revision, _approval, publication = await _prepared_flow(
            client, settings, connection_id
        )
        assert revision["text_sha256"] == utc_text_sha256("Exact synthetic Stage 1 text.\n")
        assert publication["status"] == "PREPARED"

        revision_replay = await client.post(
            f"/v1/drafts/{draft['id']}/revisions",
            json={"text": "Exact synthetic Stage 1 text.\n", "created_by": "owner"},
            headers=_headers(settings, "flow-revision-key-0001"),
        )
        approval_replay = await client.post(
            f"/v1/revisions/{revision['id']}/approve",
            json={"approved_by": "owner"},
            headers=_headers(settings, "flow-approval-key-0001"),
        )
        prepare_replay = await client.post(
            "/v1/publications/prepare",
            json={
                "revision_id": revision["id"],
                "approval_id": _approval["id"],
                "connection_id": str(connection_id),
            },
            headers=_headers(settings, "flow-prepare-key-0001"),
        )
        assert revision_replay.status_code == 200
        assert revision_replay.json()["id"] == revision["id"]
        assert approval_replay.status_code == 200
        assert approval_replay.json()["id"] == _approval["id"]
        assert prepare_replay.status_code == 200
        assert prepare_replay.json()["id"] == publication["id"]

        execute_headers = _headers(settings, "flow-execute-key-0001")
        executed = await client.post(
            f"/v1/publications/{publication['id']}/execute",
            json={"confirm_execute": True},
            headers=execute_headers,
        )
        assert executed.status_code == 200
        assert executed.json()["status"] == "PUBLISHED"
        replay = await client.post(
            f"/v1/publications/{publication['id']}/execute",
            json={"confirm_execute": True},
            headers=execute_headers,
        )
        assert replay.status_code == 200
        assert replay.json()["status"] == "PUBLISHED"
        assert publisher.call_count == 1
        assert token not in caplog.text
        assert settings.owner_key.get_secret_value() not in caplog.text
        assert "PUBLISHING->PUBLISHED" in caplog.text
        audit = await client.get(
            f"/v1/drafts/{draft['id']}/audit",
            headers={"X-Owner-Key": settings.owner_key.get_secret_value()},
        )
        event_types = [event["event_type"] for event in audit.json()]
        assert event_types == [
            "DRAFT_CREATED",
            "REVISION_CREATED",
            "APPROVAL_GRANTED",
            "PUBLICATION_PREPARED",
            "PUBLICATION_STARTED",
            "PUBLICATION_SUCCEEDED",
        ]

    sessions = sessionmaker(stage1_engine)
    with sessions() as session:
        connection = session.get(LinkedInConnection, connection_id)
        assert connection is not None
        assert connection.encrypted_access_token.startswith("v1:primary:")
        assert token not in connection.encrypted_access_token
        assert token not in repr(connection)
        attempts = session.scalars(select(PublicationAttempt)).all()
        assert len(attempts) == 1
        with pytest.raises(IntegrityError):
            session.add(
                PublicationAttempt(
                    publication_id=attempts[0].publication_id,
                    attempt_number=1,
                    stage="FINAL_POST",
                    outcome="STARTED",
                )
            )
            session.commit()
        session.rollback()

    restarted = create_app(
        settings,
        stage1_engine=stage1_engine,
        stage1_publisher=FakeLinkedInPublisher(),
    )
    async for client in _client(restarted):
        persisted = await client.get(
            f"/v1/publications/{publication['id']}",
            headers={"X-Owner-Key": settings.owner_key.get_secret_value()},
        )
        assert persisted.status_code == 200
        assert persisted.json()["status"] == "PUBLISHED"

    disabled_settings = _stage1_settings(
        settings_factory,
        TEST_DATABASE_URL,
        linkedin_publisher_mode="disabled",
    )
    disabled_restart = create_app(disabled_settings, stage1_engine=stage1_engine)
    async for client in _client(disabled_restart):
        terminal_replay = await client.post(
            f"/v1/publications/{publication['id']}/execute",
            json={"confirm_execute": True},
            headers=_headers(disabled_settings, "flow-execute-key-0001"),
        )
        assert terminal_replay.status_code == 200
        assert terminal_replay.json()["status"] == "PUBLISHED"


@pytest.mark.asyncio
async def test_owner_auth_idempotency_conflict_and_stale_revision(
    settings_factory: Callable[..., Settings],
    stage1_engine: Engine,
) -> None:
    assert TEST_DATABASE_URL is not None
    settings = _stage1_settings(settings_factory, TEST_DATABASE_URL)
    app = create_app(
        settings,
        stage1_engine=stage1_engine,
        stage1_publisher=FakeLinkedInPublisher(),
    )
    async for client in _client(app):
        missing = await client.post(
            "/v1/drafts",
            json={"title": "one"},
            headers={"Idempotency-Key": "auth-draft-key-0001"},
        )
        wrong = await client.post(
            "/v1/drafts",
            json={"title": "one"},
            headers={
                "X-Owner-Key": "wrong-owner-key",
                "Idempotency-Key": "auth-draft-key-0001",
            },
        )
        assert missing.status_code == 401
        assert wrong.status_code == 403
        not_found = await client.get(
            f"/v1/drafts/{uuid.uuid4()}",
            headers={"X-Owner-Key": settings.owner_key.get_secret_value()},
        )
        invalid = await client.post(
            "/v1/drafts",
            json={"title": "one", "unexpected": True},
            headers=_headers(settings, "validation-draft-key-0001"),
        )
        assert not_found.status_code == 404
        assert invalid.status_code == 422

        headers = _headers(settings, "same-draft-key-0001")
        first = await client.post("/v1/drafts", json={"title": "one"}, headers=headers)
        replay = await client.post("/v1/drafts", json={"title": "one"}, headers=headers)
        conflict = await client.post("/v1/drafts", json={"title": "two"}, headers=headers)
        assert first.status_code == 201
        assert replay.status_code == 200
        assert replay.json()["id"] == first.json()["id"]
        assert conflict.status_code == 409

        revision_one = await client.post(
            f"/v1/drafts/{first.json()['id']}/revisions",
            json={"text": "v1", "created_by": "owner"},
            headers=_headers(settings, "stale-revision-key-0001"),
        )
        revision_two = await client.post(
            f"/v1/drafts/{first.json()['id']}/revisions",
            json={"text": "v2", "created_by": "owner"},
            headers=_headers(settings, "stale-revision-key-0002"),
        )
        stale = await client.post(
            f"/v1/revisions/{revision_one.json()['id']}/approve",
            json={"approved_by": "owner"},
            headers=_headers(settings, "stale-approval-key-0001"),
        )
        assert revision_two.status_code == 201
        assert revision_one.json()["revision_number"] == 1
        assert revision_two.json()["revision_number"] == 2
        assert stale.status_code == 409
        assert stale.json()["code"] == "STALE_REVISION"


@pytest.mark.asyncio
async def test_old_and_revoked_approvals_cannot_publish_and_revision_is_immutable(
    settings_factory: Callable[..., Settings],
    stage1_engine: Engine,
) -> None:
    assert TEST_DATABASE_URL is not None
    settings = _stage1_settings(settings_factory, TEST_DATABASE_URL)
    app = create_app(
        settings,
        stage1_engine=stage1_engine,
        stage1_publisher=FakeLinkedInPublisher(),
    )
    connection_id = _import_connection(app, settings)
    async for client in _client(app):
        draft_response = await client.post(
            "/v1/drafts",
            json={"title": "Approval invalidation"},
            headers=_headers(settings, "approval-guard-draft-0001"),
        )
        draft_id = draft_response.json()["id"]
        revision_one = await client.post(
            f"/v1/drafts/{draft_id}/revisions",
            json={"text": "first exact revision", "created_by": "owner"},
            headers=_headers(settings, "approval-guard-revision-0001"),
        )
        approval_one = await client.post(
            f"/v1/revisions/{revision_one.json()['id']}/approve",
            json={"approved_by": "owner"},
            headers=_headers(settings, "approval-guard-approval-0001"),
        )
        revision_two = await client.post(
            f"/v1/drafts/{draft_id}/revisions",
            json={"text": "second exact revision", "created_by": "owner"},
            headers=_headers(settings, "approval-guard-revision-0002"),
        )
        stale_prepare = await client.post(
            "/v1/publications/prepare",
            json={
                "revision_id": revision_one.json()["id"],
                "approval_id": approval_one.json()["id"],
                "connection_id": str(connection_id),
            },
            headers=_headers(settings, "approval-guard-prepare-0001"),
        )
        assert stale_prepare.status_code == 409
        assert stale_prepare.json()["code"] == "STALE_REVISION"

        approval_two = await client.post(
            f"/v1/revisions/{revision_two.json()['id']}/approve",
            json={"approved_by": "owner"},
            headers=_headers(settings, "approval-guard-approval-0002"),
        )
        revoked = await client.post(
            f"/v1/approvals/{approval_two.json()['id']}/revoke",
            json={"reason": "owner changed decision"},
            headers={"X-Owner-Key": settings.owner_key.get_secret_value()},
        )
        revoked_prepare = await client.post(
            "/v1/publications/prepare",
            json={
                "revision_id": revision_two.json()["id"],
                "approval_id": approval_two.json()["id"],
                "connection_id": str(connection_id),
            },
            headers=_headers(settings, "approval-guard-prepare-0002"),
        )
        assert revoked.status_code == 200
        assert revoked_prepare.status_code == 409
        assert revoked_prepare.json()["code"] == "APPROVAL_REVOKED"

    with stage1_engine.begin() as connection, pytest.raises(DBAPIError):
        connection.execute(
            text("UPDATE post_revisions SET text = 'mutated' WHERE id = :id"),
            {"id": uuid.UUID(revision_two.json()["id"])},
        )


@pytest.mark.parametrize(
    ("outcome", "expected"),
    [
        ("4xx", "FAILED"),
        ("timeout", "PUBLISH_UNCERTAIN"),
        ("connection-reset", "PUBLISH_UNCERTAIN"),
        ("5xx", "PUBLISH_UNCERTAIN"),
        ("response-lost", "PUBLISH_UNCERTAIN"),
    ],
)
@pytest.mark.asyncio
async def test_publication_failure_classification_and_no_retry(
    settings_factory: Callable[..., Settings],
    stage1_engine: Engine,
    outcome: str,
    expected: str,
) -> None:
    assert TEST_DATABASE_URL is not None
    settings = _stage1_settings(settings_factory, TEST_DATABASE_URL)
    publisher = FakeLinkedInPublisher(outcome)
    app = create_app(settings, stage1_engine=stage1_engine, stage1_publisher=publisher)
    connection_id = _import_connection(app, settings)
    async for client in _client(app):
        _, _, _, publication = await _prepared_flow(client, settings, connection_id, prefix=outcome)
        headers = _headers(settings, f"{outcome}-execute-key-0001")
        executed = await client.post(
            f"/v1/publications/{publication['id']}/execute",
            json={"confirm_execute": True},
            headers=headers,
        )
        assert executed.json()["status"] == expected
        replay = await client.post(
            f"/v1/publications/{publication['id']}/execute",
            json={"confirm_execute": True},
            headers=headers,
        )
        assert replay.json()["status"] == expected
        assert publisher.call_count == 1


class GatePublisher:
    available = True

    def __init__(self) -> None:
        self.call_count = 0
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def create_text_post(self, command: TextPostCommand) -> TextPostReceipt:
        del command
        self.call_count += 1
        self.started.set()
        await self.release.wait()
        return TextPostReceipt("urn:li:share:concurrent-synthetic")


class CancelledPublisher:
    available = True

    async def create_text_post(self, command: TextPostCommand) -> TextPostReceipt:
        del command
        raise asyncio.CancelledError


class UnexpectedPublisher:
    available = True

    def __init__(self) -> None:
        self.call_count = 0

    async def create_text_post(self, command: TextPostCommand) -> TextPostReceipt:
        del command
        self.call_count += 1
        raise RuntimeError("opaque adapter failure that must not escape")


class InvalidReceiptPublisher:
    available = True

    def __init__(self) -> None:
        self.call_count = 0

    async def create_text_post(self, command: TextPostCommand) -> TextPostReceipt:
        del command
        self.call_count += 1
        return TextPostReceipt("", http_status=201)


@pytest.mark.asyncio
async def test_concurrent_execute_creates_one_attempt_and_one_adapter_call(
    settings_factory: Callable[..., Settings],
    stage1_engine: Engine,
) -> None:
    assert TEST_DATABASE_URL is not None
    settings = _stage1_settings(settings_factory, TEST_DATABASE_URL)
    publisher = GatePublisher()
    app = create_app(settings, stage1_engine=stage1_engine, stage1_publisher=publisher)
    connection_id = _import_connection(app, settings)
    async for client in _client(app):
        _, _, _, publication = await _prepared_flow(
            client, settings, connection_id, prefix="concurrent"
        )
        first = asyncio.create_task(
            client.post(
                f"/v1/publications/{publication['id']}/execute",
                json={"confirm_execute": True},
                headers=_headers(settings, "concurrent-execute-key-0001"),
            )
        )
        await publisher.started.wait()
        second = await client.post(
            f"/v1/publications/{publication['id']}/execute",
            json={"confirm_execute": True},
            headers=_headers(settings, "concurrent-execute-key-0002"),
        )
        assert second.json()["status"] == "PUBLISHING"
        publisher.release.set()
        completed = await first
        assert completed.json()["status"] == "PUBLISHED"
        assert publisher.call_count == 1
        assert (
            app.state.stage1_services.publication_attempt_count(uuid.UUID(publication["id"])) == 1
        )


@pytest.mark.asyncio
async def test_cancellation_after_execution_start_is_persisted_uncertain(
    settings_factory: Callable[..., Settings],
    stage1_engine: Engine,
) -> None:
    assert TEST_DATABASE_URL is not None
    settings = _stage1_settings(settings_factory, TEST_DATABASE_URL)
    app = create_app(
        settings,
        stage1_engine=stage1_engine,
        stage1_publisher=CancelledPublisher(),
    )
    connection_id = _import_connection(app, settings)
    publication_id: uuid.UUID | None = None
    async for client in _client(app):
        _, _, _, publication = await _prepared_flow(
            client, settings, connection_id, prefix="cancelled"
        )
        publication_id = uuid.UUID(publication["id"])
        with pytest.raises((asyncio.CancelledError, RuntimeError), match="No response returned"):
            await client.post(
                f"/v1/publications/{publication['id']}/execute",
                json={"confirm_execute": True},
                headers=_headers(settings, "cancelled-execute-key-0001"),
            )
    assert publication_id is not None
    persisted = app.state.stage1_services.publications.get(publication_id)
    assert persisted.status == "PUBLISH_UNCERTAIN"
    assert persisted.safe_error_code == "FINAL_REQUEST_CANCELLED"


@pytest.mark.asyncio
async def test_pre_network_token_failure_is_terminal_without_adapter_call(
    settings_factory: Callable[..., Settings],
    stage1_engine: Engine,
) -> None:
    assert TEST_DATABASE_URL is not None
    settings = _stage1_settings(settings_factory, TEST_DATABASE_URL)
    publisher = FakeLinkedInPublisher()
    app = create_app(settings, stage1_engine=stage1_engine, stage1_publisher=publisher)
    connection_id = _import_connection(app, settings)
    async for client in _client(app):
        _, _, _, publication = await _prepared_flow(
            client, settings, connection_id, prefix="decrypt-failure"
        )
        with sessionmaker(stage1_engine).begin() as session:
            connection = session.get(LinkedInConnection, connection_id)
            assert connection is not None
            connection.encrypted_access_token = "v1:primary:invalid"
        response = await client.post(
            f"/v1/publications/{publication['id']}/execute",
            json={"confirm_execute": True},
            headers=_headers(settings, "decrypt-failure-execute-key-0001"),
        )
        assert response.status_code == 200
        assert response.json()["status"] == "FAILED"
        assert response.json()["safe_error_code"] == "TOKEN_DECRYPTION_FAILED"
        assert response.json()["request_attempted"] is False
        assert publisher.call_count == 0


@pytest.mark.parametrize("publisher_type", [UnexpectedPublisher, InvalidReceiptPublisher])
@pytest.mark.asyncio
async def test_unconfirmed_adapter_outcome_is_uncertain_and_never_retried(
    settings_factory: Callable[..., Settings],
    stage1_engine: Engine,
    publisher_type: type[UnexpectedPublisher] | type[InvalidReceiptPublisher],
) -> None:
    assert TEST_DATABASE_URL is not None
    settings = _stage1_settings(settings_factory, TEST_DATABASE_URL)
    publisher = publisher_type()
    app = create_app(settings, stage1_engine=stage1_engine, stage1_publisher=publisher)
    connection_id = _import_connection(app, settings)
    async for client in _client(app):
        _, _, _, publication = await _prepared_flow(
            client, settings, connection_id, prefix=publisher_type.__name__
        )
        headers = _headers(settings, f"{publisher_type.__name__}-execute-key-0001")
        response = await client.post(
            f"/v1/publications/{publication['id']}/execute",
            json={"confirm_execute": True},
            headers=headers,
        )
        replay = await client.post(
            f"/v1/publications/{publication['id']}/execute",
            json={"confirm_execute": True},
            headers=headers,
        )
        assert response.status_code == 200
        assert response.json()["status"] == "PUBLISH_UNCERTAIN"
        assert replay.json()["status"] == "PUBLISH_UNCERTAIN"
        assert publisher.call_count == 1


def test_audit_metadata_rejects_nested_secret_fields() -> None:
    with Session() as session, pytest.raises(DomainError, match="UNSAFE_AUDIT_METADATA"):
        AuditService.record(
            session,
            aggregate_type="DRAFT",
            aggregate_id=uuid.uuid4(),
            event_type="DRAFT_CREATED",
            actor_id="owner",
            request_id="nested-secret-test",
            safe_metadata={"nested": [{"authorization_header": "must-not-be-stored"}]},
        )


def test_database_constraints_and_append_only_records(stage1_engine: Engine) -> None:
    sessions = sessionmaker(stage1_engine)
    revision = PostRevision(
        draft_id=uuid.uuid4(),
        revision_number=1,
        text="orphan",
        text_sha256=utc_text_sha256("orphan"),
        canonicalization_version=CANONICALIZATION_VERSION,
        created_by="owner",
    )
    with sessions() as session, pytest.raises(IntegrityError):
        session.add(revision)
        session.commit()

    with stage1_engine.begin() as connection:
        aggregate_id = uuid.uuid4()
        event_id = uuid.uuid4()
        connection.execute(
            text(
                """
                INSERT INTO audit_events
                  (id, aggregate_type, aggregate_id, event_type, actor_type, actor_id,
                   request_id, occurred_at, safe_metadata)
                VALUES
                  (:id, 'DRAFT', :aggregate_id, 'DRAFT_CREATED', 'OWNER', 'owner',
                   'append-only-test', now(), '{}'::jsonb)
                """
            ),
            {"id": event_id, "aggregate_id": aggregate_id},
        )
    with stage1_engine.begin() as connection, pytest.raises(DBAPIError):
        connection.execute(
            text("UPDATE audit_events SET event_type = 'MUTATED' WHERE id = :id"),
            {"id": event_id},
        )


def test_stale_reconciliation_never_calls_publisher(
    settings_factory: Callable[..., Settings],
    stage1_engine: Engine,
) -> None:
    assert TEST_DATABASE_URL is not None
    settings = _stage1_settings(settings_factory, TEST_DATABASE_URL)
    publisher = FakeLinkedInPublisher()
    app = create_app(settings, stage1_engine=stage1_engine, stage1_publisher=publisher)
    connection_id = _import_connection(app, settings)
    sessions: sessionmaker[Session] = sessionmaker(stage1_engine)
    services = app.state.stage1_services
    draft, _ = services.drafts.create(
        title=None,
        idempotency_key="reconcile-draft-key-0001",
        actor="owner",
        request_id="reconcile",
    )
    revision, _ = services.revisions.create(
        draft_id=draft.id,
        text="reconcile text",
        created_by="owner",
        idempotency_key="reconcile-revision-key-0001",
        request_id="reconcile",
    )
    approval, _ = services.approvals.approve(
        revision_id=revision.id,
        approved_by="owner",
        idempotency_key="reconcile-approval-key-0001",
        request_id="reconcile",
    )
    publication, _ = services.publications.prepare(
        revision_id=revision.id,
        approval_id=approval.id,
        connection_id=connection_id,
        idempotency_key="reconcile-prepare-key-0001",
        actor="owner",
        request_id="reconcile",
    )
    with sessions.begin() as session:
        persisted = session.get(type(publication), publication.id)
        assert persisted is not None
        persisted.status = PublicationStatus.PUBLISHING.value
        persisted.started_at = datetime.now(UTC) - timedelta(hours=1)
        session.add(
            PublicationAttempt(
                publication_id=publication.id,
                attempt_number=1,
                stage="FINAL_POST",
                outcome="STARTED",
            )
        )
    dry_run = services.publications.reconcile_stale(threshold_seconds=300, confirm=False)
    assert dry_run == [publication.id]
    confirmed = services.publications.reconcile_stale(threshold_seconds=300, confirm=True)
    assert confirmed == [publication.id]
    assert services.publications.get(publication.id).status == "PUBLISH_UNCERTAIN"
    assert publisher.call_count == 0


@pytest.mark.asyncio
async def test_live_disabled_by_default_preserves_prepared(
    settings_factory: Callable[..., Settings],
    stage1_engine: Engine,
) -> None:
    assert TEST_DATABASE_URL is not None
    settings = _stage1_settings(
        settings_factory,
        TEST_DATABASE_URL,
        linkedin_publisher_mode="disabled",
    )
    app = create_app(settings, stage1_engine=stage1_engine)
    assert app.state.stage1_publisher.available is False
    connection_id = _import_connection(app, settings)
    async for client in _client(app):
        _, _, _, publication = await _prepared_flow(
            client, settings, connection_id, prefix="disabled"
        )
        missing_confirmation = await client.post(
            f"/v1/publications/{publication['id']}/execute",
            json={"confirm_execute": False},
            headers=_headers(settings, "disabled-execute-key-0000"),
        )
        response = await client.post(
            f"/v1/publications/{publication['id']}/execute",
            json={"confirm_execute": True},
            headers=_headers(settings, "disabled-execute-key-0001"),
        )
        assert missing_confirmation.status_code == 400
        assert missing_confirmation.json()["code"] == "EXECUTION_CONFIRMATION_REQUIRED"
        assert response.status_code == 409
        assert response.json()["code"] == "LINKEDIN_PUBLISHING_DISABLED"
        persisted = await client.get(
            f"/v1/publications/{publication['id']}",
            headers={"X-Owner-Key": settings.owner_key.get_secret_value()},
        )
        assert persisted.json()["status"] == "PREPARED"


@pytest.mark.asyncio
async def test_readiness_and_static_openapi_match_routes(
    settings_factory: Callable[..., Settings],
    stage1_engine: Engine,
) -> None:
    assert TEST_DATABASE_URL is not None
    settings = _stage1_settings(settings_factory, TEST_DATABASE_URL)
    app = create_app(
        settings,
        stage1_engine=stage1_engine,
        stage1_publisher=FakeLinkedInPublisher(),
    )
    async for client in _client(app):
        ready = await client.get("/ready")
        assert ready.status_code == 200
        assert ready.json()["mutations"] is True

    static_spec = yaml.safe_load(Path("specs/openapi.yaml").read_text(encoding="utf-8"))
    generated = app.openapi()
    for path, operations in static_spec["paths"].items():
        assert path in generated["paths"]
        for method in operations:
            assert method in generated["paths"][path]

    unavailable_engine = create_engine(
        "postgresql+psycopg://publisher:unused@127.0.0.1:1/publisher",
        connect_args={"connect_timeout": 1},
    )
    try:
        unavailable = create_app(
            settings,
            stage1_engine=unavailable_engine,
            stage1_publisher=FakeLinkedInPublisher(),
        )
        async for client in _client(unavailable):
            response = await client.get("/ready")
            assert response.status_code == 503
            assert response.json()["mutations"] is False
    finally:
        unavailable_engine.dispose()
