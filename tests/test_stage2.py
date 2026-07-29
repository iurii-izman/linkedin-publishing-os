from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
import yaml
from fastapi import FastAPI
from pydantic import SecretStr, ValidationError
from sqlalchemy import Engine, create_engine, text

from publisher_api.main import create_app
from publisher_api.settings import Settings
from publisher_api.stage1_publisher import FakeLinkedInPublisher
from publisher_api.stage2_services import callback_token_hash
from publisher_api.stage2_telegram import (
    FakeTelegramGateway,
    approval_message,
    result_message,
)
from publisher_api.token_store import EncryptedConnectionStore, StoredConnection

TEST_DATABASE_URL = os.getenv("STAGE1_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="STAGE1_TEST_DATABASE_URL is required for PostgreSQL integration tests",
)

OWNER_USER_ID = 10001
OWNER_CHAT_ID = 20002
OWNER_KEY = "synthetic-stage2-owner-key-with-32-characters"
SERVICE_KEY = "synthetic-n8n-service-key-with-32-characters"


@pytest.fixture(scope="session")
def stage2_engine() -> Iterator[Engine]:
    assert TEST_DATABASE_URL is not None
    engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    yield engine
    engine.dispose()


@pytest.fixture(autouse=True)
def clean_stage2_database(stage2_engine: Engine) -> Iterator[None]:
    tables = [
        "telegram_deliveries",
        "external_approval_requests",
        "publication_attempts",
        "idempotency_records",
        "publications",
        "approvals",
        "linkedin_connections",
        "audit_events",
        "drafts",
        "post_revisions",
    ]
    with stage2_engine.begin() as connection:
        connection.execute(text(f"TRUNCATE TABLE {', '.join(tables)} RESTART IDENTITY CASCADE"))
    yield


def stage2_settings(
    settings_factory: Callable[..., Settings],
    **overrides: object,
) -> Settings:
    assert TEST_DATABASE_URL is not None
    values: dict[str, object] = {
        "database_url": TEST_DATABASE_URL,
        "app_owner_key": OWNER_KEY,
        "n8n_service_key": SERVICE_KEY,
        "telegram_owner_user_id": OWNER_USER_ID,
        "telegram_owner_chat_id": OWNER_CHAT_ID,
        "approval_request_ttl_seconds": 300,
        "linkedin_publisher_mode": "fake-success",
    }
    values.update(overrides)
    return settings_factory(**values)


async def client_for(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://stage2.example.test",
    ) as client:
        yield client


def owner_headers(key: str) -> dict[str, str]:
    return {"X-Owner-Key": OWNER_KEY, "Idempotency-Key": key}


def service_headers(key: str | None = None) -> dict[str, str]:
    headers = {"X-N8N-Service-Key": SERVICE_KEY}
    if key is not None:
        headers["Idempotency-Key"] = key
    return headers


async def create_revision(
    client: httpx.AsyncClient, *, prefix: str = "stage2", text_value: str = "Exact preview."
) -> tuple[dict[str, Any], dict[str, Any]]:
    draft_response = await client.post(
        "/v1/drafts",
        json={"title": "Synthetic Telegram approval"},
        headers=owner_headers(f"{prefix}-draft-idempotency"),
    )
    assert draft_response.status_code == 201
    draft = draft_response.json()
    revision_response = await client.post(
        f"/v1/drafts/{draft['id']}/revisions",
        json={"text": text_value, "created_by": "owner"},
        headers=owner_headers(f"{prefix}-revision-idempotency"),
    )
    assert revision_response.status_code == 201
    return draft, revision_response.json()


async def create_external_request(
    client: httpx.AsyncClient,
    revision_id: str,
    *,
    key: str = "stage2-request-idempotency",
) -> dict[str, Any]:
    response = await client.post(
        f"/v1/revisions/{revision_id}/external-approval-requests",
        json={"requested_by": "owner"},
        headers=owner_headers(key),
    )
    assert response.status_code == 201
    return cast(dict[str, Any], response.json())


def import_connection(app: FastAPI, settings: Settings) -> uuid.UUID:
    stored = StoredConnection(
        access_token=SecretStr("AQ-synthetic-stage2-token"),
        expires_at=datetime.now(UTC) + timedelta(days=1),
        granted_scopes=["openid", "profile", "w_member_social"],
        member_subject="stage2-member",
        author_urn="urn:li:person:stage2-member",
        api_version="202607",
    )
    EncryptedConnectionStore(settings.stage0_token_store_path, settings.token_encryption_key).save(
        stored
    )
    result = app.state.stage1_services.connections.import_stage0(confirm=True)
    return uuid.UUID(result["connection_id"])


def decision_body(token: str, decision: str = "APPROVE_AND_PUBLISH") -> dict[str, Any]:
    return {
        "callback_token": token,
        "telegram_user_id": OWNER_USER_ID,
        "telegram_chat_id": OWNER_CHAT_ID,
        "decision": decision,
        "callback_query_id": "callback-query-1",
        "message_external_id": "telegram-message-1",
    }


@pytest.mark.asyncio
async def test_create_request_binds_exact_current_revision_and_preview(
    settings_factory: Callable[..., Settings], stage2_engine: Engine
) -> None:
    settings = stage2_settings(settings_factory)
    app = create_app(settings, stage1_engine=stage2_engine)
    async for client in client_for(app):
        draft, revision = await create_revision(
            client, text_value="Exact Telegram preview.\nSecond line."
        )
        request = await create_external_request(client, revision["id"])
        assert request["draft_id"] == draft["id"]
        assert request["revision_id"] == revision["id"]
        assert request["revision_sha256_prefix"] == revision["text_sha256"][:12]
        assert request["preview"]["exact_text"] == "Exact Telegram preview.\nSecond line."
        assert request["preview"]["text_length"] == len("Exact Telegram preview.\nSecond line.")
        assert request["callback_token"]


@pytest.mark.asyncio
async def test_callback_token_is_hashed_and_returned_only_once(
    settings_factory: Callable[..., Settings], stage2_engine: Engine
) -> None:
    settings = stage2_settings(settings_factory)
    app = create_app(settings, stage1_engine=stage2_engine)
    async for client in client_for(app):
        _, revision = await create_revision(client)
        request = await create_external_request(client, revision["id"])
        token = request["callback_token"]
        replay = await client.post(
            f"/v1/revisions/{revision['id']}/external-approval-requests",
            json={"requested_by": "owner"},
            headers=owner_headers("stage2-request-idempotency"),
        )
        assert replay.status_code == 200
        assert replay.json()["callback_token"] is None
        with stage2_engine.connect() as connection:
            stored = connection.execute(
                text("select callback_token_hash from external_approval_requests where id=:id"),
                {"id": request["id"]},
            ).scalar_one()
        assert stored == callback_token_hash(token)
        assert token != stored


@pytest.mark.asyncio
async def test_stale_revision_rejected_and_pending_request_invalidated(
    settings_factory: Callable[..., Settings], stage2_engine: Engine
) -> None:
    settings = stage2_settings(settings_factory)
    app = create_app(settings, stage1_engine=stage2_engine)
    async for client in client_for(app):
        draft, revision = await create_revision(client)
        request = await create_external_request(client, revision["id"])
        new_revision = await client.post(
            f"/v1/drafts/{draft['id']}/revisions",
            json={"text": "Changed text.", "created_by": "owner"},
            headers=owner_headers("changed-revision-idempotency"),
        )
        assert new_revision.status_code == 201
        old_request = await client.get(
            f"/v1/external-approval-requests/{request['id']}",
            headers={"X-Owner-Key": OWNER_KEY},
        )
        decision = await client.post(
            "/v1/orchestration/approval-decisions",
            json=decision_body(request["callback_token"]),
            headers=service_headers("stale-decision-idempotency"),
        )
        assert old_request.json()["status"] == "INVALIDATED"
        assert decision.status_code == 409


@pytest.mark.asyncio
async def test_expired_callback_rejected(
    settings_factory: Callable[..., Settings], stage2_engine: Engine
) -> None:
    settings = stage2_settings(settings_factory)
    app = create_app(settings, stage1_engine=stage2_engine)
    async for client in client_for(app):
        _, revision = await create_revision(client)
        request = await create_external_request(client, revision["id"])
        with stage2_engine.begin() as connection:
            connection.execute(
                text(
                    "update external_approval_requests "
                    "set expires_at=now()-interval '1 second' where id=:id"
                ),
                {"id": request["id"]},
            )
        response = await client.post(
            "/v1/orchestration/approval-decisions",
            json=decision_body(request["callback_token"]),
            headers=service_headers("expired-decision-idempotency"),
        )
        assert response.status_code == 409
        with stage2_engine.connect() as connection:
            status = connection.execute(
                text("select status from external_approval_requests where id=:id"),
                {"id": request["id"]},
            ).scalar_one()
        assert status == "EXPIRED"


@pytest.mark.asyncio
async def test_owner_can_invalidate_pending_request(
    settings_factory: Callable[..., Settings], stage2_engine: Engine
) -> None:
    settings = stage2_settings(settings_factory)
    app = create_app(settings, stage1_engine=stage2_engine)
    async for client in client_for(app):
        _, revision = await create_revision(client)
        request = await create_external_request(client, revision["id"])
        response = await client.post(
            f"/v1/external-approval-requests/{request['id']}/invalidate",
            json={"reason": "Owner cancelled"},
            headers={"X-Owner-Key": OWNER_KEY},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "INVALIDATED"


@pytest.mark.asyncio
async def test_reject_is_terminal_and_creates_no_approval_or_publication(
    settings_factory: Callable[..., Settings], stage2_engine: Engine
) -> None:
    settings = stage2_settings(settings_factory)
    app = create_app(settings, stage1_engine=stage2_engine)
    async for client in client_for(app):
        _, revision = await create_revision(client)
        request = await create_external_request(client, revision["id"])
        response = await client.post(
            "/v1/orchestration/approval-decisions",
            json=decision_body(request["callback_token"], "REJECT"),
            headers=service_headers("reject-decision-idempotency"),
        )
        assert response.status_code == 200
        assert response.json()["status"] == "REJECTED"
        assert response.json()["next_action"] == "STOP"
        with stage2_engine.connect() as connection:
            assert connection.execute(text("select count(*) from approvals")).scalar_one() == 0
            assert connection.execute(text("select count(*) from publications")).scalar_one() == 0


@pytest.mark.asyncio
async def test_approve_replay_and_conflicting_decision(
    settings_factory: Callable[..., Settings], stage2_engine: Engine
) -> None:
    settings = stage2_settings(settings_factory)
    app = create_app(settings, stage1_engine=stage2_engine)
    async for client in client_for(app):
        _, revision = await create_revision(client)
        request = await create_external_request(client, revision["id"])
        first = await client.post(
            "/v1/orchestration/approval-decisions",
            json=decision_body(request["callback_token"]),
            headers=service_headers("approve-decision-idempotency"),
        )
        replay = await client.post(
            "/v1/orchestration/approval-decisions",
            json=decision_body(request["callback_token"]),
            headers=service_headers("approve-decision-replay-key"),
        )
        conflict = await client.post(
            "/v1/orchestration/approval-decisions",
            json=decision_body(request["callback_token"], "REJECT"),
            headers=service_headers("approve-decision-conflict"),
        )
        assert first.status_code == 200
        assert replay.json()["replayed"] is True
        assert replay.json()["approval_id"] == first.json()["approval_id"]
        assert conflict.status_code == 409
        with stage2_engine.connect() as connection:
            assert connection.execute(text("select count(*) from approvals")).scalar_one() == 1


@pytest.mark.asyncio
async def test_concurrent_approve_creates_one_approval(
    settings_factory: Callable[..., Settings], stage2_engine: Engine
) -> None:
    settings = stage2_settings(settings_factory)
    app = create_app(settings, stage1_engine=stage2_engine)
    async for client in client_for(app):
        _, revision = await create_revision(client)
        request = await create_external_request(client, revision["id"])

        callback_token = request["callback_token"]
        client_ref = client

        async def decide(
            key_value: str,
            client_bound: httpx.AsyncClient = client_ref,
            token_bound: str = callback_token,
        ) -> httpx.Response:
            return await client_bound.post(
                "/v1/orchestration/approval-decisions",
                json=decision_body(token_bound),
                headers=service_headers(key_value),
            )

        responses = await asyncio.gather(
            decide("concurrent-decision-key-0001"),
            decide("concurrent-decision-key-0002"),
        )
        assert all(response.status_code == 200 for response in responses)
        with stage2_engine.connect() as connection:
            assert connection.execute(text("select count(*) from approvals")).scalar_one() == 1


@pytest.mark.asyncio
async def test_offline_approve_prepare_execute_and_replays(
    settings_factory: Callable[..., Settings], stage2_engine: Engine
) -> None:
    settings = stage2_settings(settings_factory)
    publisher = FakeLinkedInPublisher()
    app = create_app(settings, stage1_engine=stage2_engine, stage1_publisher=publisher)
    connection_id = import_connection(app, settings)
    async for client in client_for(app):
        _, revision = await create_revision(client, prefix="e2e")
        request = await create_external_request(
            client, revision["id"], key="e2e-request-idempotency"
        )
        preview = await client.get(
            f"/v1/orchestration/approval-requests/{request['id']}/preview",
            headers=service_headers(),
        )
        assert preview.status_code == 200
        gateway = FakeTelegramGateway()
        message_id = gateway.send(
            text=approval_message(preview.json()),
            callback_actions=["APPROVE_AND_PUBLISH", "REJECT"],
        )
        delivery = await client.post(
            f"/v1/orchestration/approval-requests/{request['id']}/delivery-result",
            json={
                "phase": "PREVIEW",
                "delivery_status": "SENT",
                "message_external_id": message_id,
            },
            headers=service_headers("e2e-delivery-idempotency"),
        )
        decision = await client.post(
            "/v1/orchestration/approval-decisions",
            json=decision_body(request["callback_token"]),
            headers=service_headers("e2e-decision-idempotency"),
        )
        prepare = await client.post(
            f"/v1/orchestration/approval-requests/{request['id']}/prepare",
            json={"connection_id": str(connection_id)},
            headers=service_headers("e2e-prepare-idempotency"),
        )
        prepare_replay = await client.post(
            f"/v1/orchestration/approval-requests/{request['id']}/prepare",
            json={"connection_id": str(connection_id)},
            headers=service_headers("e2e-prepare-idempotency"),
        )
        publication_id = prepare.json()["id"]
        execute_body = {
            "approval_request_id": request["id"],
            "confirm_execute": True,
        }
        execute = await client.post(
            f"/v1/orchestration/publications/{publication_id}/execute",
            json=execute_body,
            headers=service_headers("e2e-execute-idempotency"),
        )
        execute_replay = await client.post(
            f"/v1/orchestration/publications/{publication_id}/execute",
            json=execute_body,
            headers=service_headers("e2e-execute-idempotency"),
        )
        result = await client.get(
            f"/v1/orchestration/publications/{publication_id}/result",
            headers=service_headers(),
        )
        gateway.edit(
            message_id=message_id,
            text=result_message(
                result.json()["status"],
                timestamp=datetime.now(UTC),
                identifier_present=result.json()["linkedin_post_identifier_present"],
            ),
        )
        result_delivery = await client.post(
            f"/v1/orchestration/approval-requests/{request['id']}/delivery-result",
            json={
                "phase": "RESULT",
                "delivery_status": "SENT",
                "message_external_id": message_id,
            },
            headers=service_headers("e2e-result-delivery-idempotency"),
        )
        assert delivery.status_code == 200
        assert decision.json()["status"] == "APPROVED"
        assert prepare.status_code == 200
        assert prepare_replay.json()["id"] == publication_id
        assert execute.json()["status"] == "PUBLISHED"
        assert execute_replay.json()["status"] == "PUBLISHED"
        assert result.json()["status"] == "PUBLISHED"
        assert result_delivery.status_code == 200
        assert publisher.call_count == 1
        assert [call["operation"] for call in gateway.calls] == ["send", "edit"]
        with stage2_engine.connect() as connection:
            assert (
                connection.execute(text("select count(*) from publication_attempts")).scalar_one()
                == 1
            )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("header_value", "expected"),
    [(None, 403), ("wrong-service-key-with-32-characters", 403)],
)
async def test_service_auth_rejects_missing_or_wrong_key(
    settings_factory: Callable[..., Settings],
    stage2_engine: Engine,
    header_value: str | None,
    expected: int,
) -> None:
    settings = stage2_settings(settings_factory)
    app = create_app(settings, stage1_engine=stage2_engine)
    async for client in client_for(app):
        headers = {} if header_value is None else {"X-N8N-Service-Key": header_value}
        response = await client.get(
            f"/v1/orchestration/approval-requests/{uuid.uuid4()}/preview",
            headers=headers,
        )
        assert response.status_code == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("telegram_user_id", OWNER_USER_ID + 1, "TELEGRAM_OWNER_FORBIDDEN"),
        ("telegram_chat_id", OWNER_CHAT_ID + 1, "TELEGRAM_CHAT_FORBIDDEN"),
    ],
)
async def test_fastapi_rechecks_telegram_identity(
    settings_factory: Callable[..., Settings],
    stage2_engine: Engine,
    field: str,
    value: int,
    code: str,
) -> None:
    settings = stage2_settings(settings_factory)
    app = create_app(settings, stage1_engine=stage2_engine)
    async for client in client_for(app):
        _, revision = await create_revision(client)
        request = await create_external_request(client, revision["id"])
        body = decision_body(request["callback_token"])
        body[field] = value
        response = await client.post(
            "/v1/orchestration/approval-decisions",
            json=body,
            headers=service_headers("identity-check-idempotency"),
        )
        assert response.status_code == 403
        assert response.json()["code"] == code


@pytest.mark.asyncio
async def test_callback_token_is_absent_from_logs_and_audit(
    settings_factory: Callable[..., Settings],
    stage2_engine: Engine,
    caplog: pytest.LogCaptureFixture,
) -> None:
    settings = stage2_settings(settings_factory)
    app = create_app(settings, stage1_engine=stage2_engine)
    caplog.set_level(logging.INFO)
    async for client in client_for(app):
        _, revision = await create_revision(client)
        request = await create_external_request(client, revision["id"])
        token = request["callback_token"]
        await client.post(
            "/v1/orchestration/approval-decisions",
            json=decision_body(token, "REJECT"),
            headers=service_headers("log-check-idempotency"),
        )
        assert token not in caplog.text
        with stage2_engine.connect() as connection:
            rendered = json.dumps(
                connection.execute(text("select safe_metadata from audit_events")).scalars().all()
            )
        assert token not in rendered


def test_settings_rejects_owner_and_service_key_reuse(
    settings_factory: Callable[..., Settings],
) -> None:
    with pytest.raises(ValidationError):
        settings_factory(
            app_owner_key=OWNER_KEY,
            n8n_service_key=OWNER_KEY,
        )


@pytest.mark.parametrize(
    ("status", "required_phrase"),
    [
        ("PUBLISHED", "PUBLISHED"),
        ("FAILED", "No automatic retry"),
        ("PUBLISH_UNCERTAIN", "retry is forbidden"),
    ],
)
def test_result_templates_are_safe(status: str, required_phrase: str) -> None:
    rendered = result_message(status, timestamp=datetime.now(UTC), identifier_present=True)
    assert required_phrase in rendered
    assert "access_token" not in rendered


WORKFLOW_FILES = [
    Path("n8n/workflows/send-telegram-approval.json"),
    Path("n8n/workflows/telegram-approval-decision.json"),
]


@pytest.mark.parametrize("path", WORKFLOW_FILES)
def test_workflow_exports_parse_and_are_inactive(path: Path) -> None:
    workflow = json.loads(path.read_text(encoding="utf-8"))
    assert workflow["active"] is False
    assert workflow["nodes"]
    assert workflow["connections"]


@pytest.mark.parametrize("path", WORKFLOW_FILES)
@pytest.mark.parametrize(
    "forbidden",
    [
        "api.linkedin.com",
        "/rest/posts",
        "access_token",
        "linkedin_client_secret",
        "telegram_bot_token",
        "x-owner-key",
        "bearer ",
        "postgresql://",
        ".stage0",
        "authorization_code",
    ],
)
def test_workflow_exports_have_no_forbidden_secret_or_boundary(path: Path, forbidden: str) -> None:
    content = path.read_text(encoding="utf-8").lower()
    assert forbidden not in content


@pytest.mark.parametrize(
    ("path", "expected_node"),
    [
        (WORKFLOW_FILES[0], "Get Exact Preview"),
        (WORKFLOW_FILES[0], "Send Exact Telegram Preview"),
        (WORKFLOW_FILES[0], "Persist Preview Delivery"),
        (WORKFLOW_FILES[1], "Verify Owner And Freeze Keys"),
        (WORKFLOW_FILES[1], "Acknowledge Callback"),
        (WORKFLOW_FILES[1], "Apply Persisted Decision"),
        (WORKFLOW_FILES[1], "Prepare Publication"),
        (WORKFLOW_FILES[1], "Execute Once"),
        (WORKFLOW_FILES[1], "Read Persisted Result"),
        (WORKFLOW_FILES[1], "Update Telegram Result"),
        (WORKFLOW_FILES[1], "Persist Result Delivery"),
    ],
)
def test_workflow_expected_nodes(path: Path, expected_node: str) -> None:
    workflow = json.loads(path.read_text(encoding="utf-8"))
    assert expected_node in {node["name"] for node in workflow["nodes"]}


def test_workflow_reuses_one_frozen_execute_key() -> None:
    content = WORKFLOW_FILES[1].read_text(encoding="utf-8")
    assert content.count("execute_key:'telegram-execute-'") == 1
    assert "$('Verify Owner And Freeze Keys').item.json.execute_key" in content
    assert "retry forbidden" in content.lower()
    assert "retryOnFail" not in content


def test_workflow_trigger_names_are_url_safe() -> None:
    send_workflow = json.loads(WORKFLOW_FILES[0].read_text(encoding="utf-8"))
    decision_workflow = json.loads(WORKFLOW_FILES[1].read_text(encoding="utf-8"))

    assert send_workflow["nodes"][0]["name"] == "approval-input"
    assert "approval-input" in send_workflow["connections"]
    assert decision_workflow["nodes"][0]["name"] == "telegram-callback"
    assert "telegram-callback" in decision_workflow["connections"]


def test_send_workflow_uses_n8n_inline_keyboard_parameter_shape() -> None:
    workflow = json.loads(WORKFLOW_FILES[0].read_text(encoding="utf-8"))
    node = next(item for item in workflow["nodes"] if item["name"] == "Send Exact Telegram Preview")
    parameters = node["parameters"]

    assert parameters["replyMarkup"] == "inlineKeyboard"
    assert len(parameters["inlineKeyboard"]["rows"][0]["row"]["buttons"]) == 2
    assert parameters["additionalFields"] == {"appendAttribution": False}
    assert "replyMarkup" not in parameters["additionalFields"]
    assert "inlineKeyboard" not in parameters["additionalFields"]
    assert "$('approval-input')" in json.dumps(parameters)


def test_workflow_manifest_covers_exports() -> None:
    manifest = json.loads(Path("n8n/workflows/manifest.json").read_text(encoding="utf-8"))
    listed = {entry["file"] for entry in manifest["workflows"]}
    assert listed == {path.name for path in WORKFLOW_FILES}
    assert manifest["credentials_embedded"] is False
    assert manifest["direct_linkedin_calls"] is False


def test_n8n_compose_environment_is_explicit_and_has_no_linkedin_credentials() -> None:
    compose = yaml.safe_load(Path("docker-compose.example.yml").read_text(encoding="utf-8"))
    n8n_service = compose["services"]["n8n"]
    assert "env_file" not in n8n_service
    environment_names = set(n8n_service["environment"])
    assert environment_names.isdisjoint(
        {
            "LINKEDIN_CLIENT_ID",
            "LINKEDIN_CLIENT_SECRET",
            "LINKEDIN_ACCESS_TOKEN",
            "TOKEN_ENCRYPTION_KEY",
            "STAGE0_OWNER_KEY",
            "APP_OWNER_KEY",
        }
    )


def test_fake_telegram_gateway_records_safe_metadata_only() -> None:
    gateway = FakeTelegramGateway()
    gateway.acknowledge_callback()
    gateway.send(text="Exact text", callback_actions=["APPROVE_AND_PUBLISH", "REJECT"])
    rendered = json.dumps(gateway.calls)
    assert "Exact text" not in rendered
    assert "token" not in rendered.lower()
