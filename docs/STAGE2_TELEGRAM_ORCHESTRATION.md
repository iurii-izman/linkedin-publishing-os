# Stage 2 Telegram Approval and n8n Orchestration

## Scope

This slice adds an offline-validated immediate text path:

```text
existing current revision
→ PostgreSQL external approval request
→ FastAPI exact preview
→ n8n Telegram delivery
→ owner decision
→ FastAPI exact approval
→ n8n prepare/execute orchestration
→ persisted result delivery
```

Scheduling, AI generation, RAG, media approval, analytics and a web UI remain out
of scope. Real Telegram and LinkedIn calls are prohibited until a separate
controlled validation is approved.

## Trust boundaries

- **FastAPI** owns revision validity, approval state, publication transitions,
  idempotency, audit and the only LinkedIn adapter.
- **PostgreSQL** is authoritative for approval requests, decisions, delivery
  metadata, publications and audit history.
- **n8n** fetches one server-built preview, calls authenticated orchestration
  commands and delivers Telegram UI updates. It does not calculate hashes, access
  application tables or call LinkedIn.
- **Telegram** is only the owner interface. Callback data contains an action and
  an opaque random token, never text, hashes or internal identifiers.

## Exact approval and replay protection

FastAPI creates a request only for the current immutable revision. It copies the
server-calculated revision SHA-256 and calculates the approval fingerprint.
Changing the current revision transactionally invalidates older pending requests.

The callback token is generated with a cryptographically secure random source,
returned only by the initial create response and stored only as SHA-256. It expires,
is unique, and is compared using a constant-time comparison after lookup. A row
lock serializes decisions:

- the same decision returns the persisted result;
- a different decision returns HTTP 409;
- expired, invalidated or stale requests cannot approve;
- `REJECT` never creates an Approval or Publication;
- prepare marks an approved request `CONSUMED`;
- replay after consumption reads the existing publication.

## Telegram owner allowlist

The owner user and chat IDs are runtime configuration. The decision workflow rejects
unexpected identities before a mutation, and FastAPI independently checks both
values again. Repository fixtures use synthetic IDs; real IDs are never exported.

## Service authentication

n8n uses `X-N8N-Service-Key`, a dedicated key distinct from `X-Owner-Key`.
Comparisons are constant-time. Workflow exports read the value from the n8n runtime
environment and never embed it. Requests use explicit operations, bounded body
schemas, request IDs and idempotency keys.

## Workflow import and credentials

Import both inactive exports from `n8n/workflows/`:

1. `send-telegram-approval.json`
2. `telegram-approval-decision.json`

Replace the `REPLACE_AT_IMPORT` Telegram credential references with an n8n
credential backed by the runtime bot token. Configure `N8N_SERVICE_KEY`,
`TELEGRAM_OWNER_USER_ID`, `TELEGRAM_OWNER_CHAT_ID`,
`PUBLISHER_API_INTERNAL_URL` and the selected safe connection identifier in the
runtime environment. Do not place values in workflow JSON.

The send workflow fetches the exact preview from FastAPI, sends one Telegram
message and persists delivery status. The decision workflow acknowledges the
callback, verifies the owner, persists the decision and uses one frozen prepare key
and one frozen execute key. If the execute response is lost, it reads the persisted
publication result instead of generating a second key.

The exported trigger node names are URL-safe (`approval-input` and
`telegram-callback`) because current n8n production webhook paths include the node
name. In the Telegram send node, `replyMarkup` and `inlineKeyboard` are top-level
node parameters; `additionalFields` only disables n8n attribution. This preserves
the two callback buttons after a sanitized workflow import.

## Result UX

- `PUBLISHED`: show the status, safe timestamp and whether a post identifier exists.
- `FAILED`: show only the safe category and do not offer automatic retry.
- `PUBLISH_UNCERTAIN`: explicitly forbid retry and instruct the owner to inspect
  the LinkedIn profile manually.
- `REJECTED`: confirm rejection and stop before prepare.

## Offline validation

Use a disposable PostgreSQL database and fake adapters:

```bash
uv run alembic upgrade head
uv run pytest -q tests/test_stage2.py
```

The E2E creates a draft and revision, sends an exact preview through
`FakeTelegramGateway`, applies an owner callback, prepares and executes with
`FakeLinkedInPublisher`, delivers the result and verifies callback/execute replay.
It also covers rejection, expiry and revision invalidation. Network calls to
Telegram and LinkedIn remain zero.

## Crash recovery

n8n stores no authoritative domain state. After a crash it reuses the frozen
idempotency keys and reads FastAPI:

- replayed decision returns its persisted decision;
- replayed prepare returns the existing publication;
- replayed execute returns the existing state without another adapter call;
- an unknown execute result is read from the result endpoint;
- `PUBLISH_UNCERTAIN` is terminal and requires manual verification.

## Deployment and backup

The Compose n8n service uses a pinned image, its own PostgreSQL database/user,
encrypted credentials, a named volume and a healthcheck. It has no direct access to
the publisher application schema and receives no LinkedIn credentials.

Back up the n8n database and named volume together with the runtime encryption key
managed outside the repository. Back up publisher PostgreSQL independently. Restore
into isolated databases and validate migrations, FastAPI readiness, workflow JSON
and credential decryption before enabling triggers.

## Controlled validation checkpoint

Keep `TELEGRAM_BOT_ENABLED=false` and LinkedIn live publishing disabled until the
owner separately authorizes exactly one Telegram approval message, one owner
callback and one Stage 1 text publication.
