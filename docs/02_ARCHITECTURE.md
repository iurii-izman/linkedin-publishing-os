# Architecture

## 1. Style

A small modular monolith plus external orchestration. One FastAPI application owns domain and LinkedIn integration. n8n orchestrates but does not own critical state.

## 2. Containers

```text
reverse-proxy
├── TLS termination
├── /api/* → publisher-api
├── /oauth/* → publisher-api
└── /n8n/* → n8n

publisher-api
├── HTTP API
├── domain services
├── OAuth controller
├── LinkedIn adapter
├── asset service
├── outbox
└── repositories

postgres
├── publisher database/user
└── n8n database/user

n8n
├── source workflows
├── generation workflows
├── Telegram workflows
├── scheduler
└── notifications
```

## 3. Suggested package structure

```text
src/publisher_api/
├── main.py
├── settings.py
├── api/
│   ├── health.py
│   ├── oauth.py
│   ├── evidence.py
│   ├── drafts.py
│   ├── approvals.py
│   ├── jobs.py
│   ├── assets.py
│   ├── integrations.py
│   └── metrics.py
├── domain/
│   ├── enums.py
│   ├── models.py
│   ├── transitions.py
│   ├── fingerprints.py
│   ├── policies.py
│   └── errors.py
├── application/
│   ├── commands.py
│   ├── services.py
│   ├── qa.py
│   ├── scheduler.py
│   └── outbox.py
├── integrations/linkedin/
│   ├── client.py
│   ├── oauth.py
│   ├── posts.py
│   ├── images.py
│   ├── documents.py
│   ├── analytics.py
│   ├── schemas.py
│   └── errors.py
└── infrastructure/
    ├── db.py
    ├── repositories.py
    ├── encryption.py
    ├── clock.py
    ├── storage.py
    └── logging.py
```

## 4. Dependency direction

```text
API → application → domain
                 ↘ ports/interfaces
infrastructure/integrations → interfaces
```

Domain code must not import FastAPI, SQLAlchemy, httpx, n8n or Telegram.

## 5. Key interfaces

```python
class LinkedInPublisher(Protocol):
    async def create_text_post(self, command: TextPostCommand) -> PublishReceipt: ...
    async def initialize_image(self, command: ImageInitCommand) -> UploadReservation: ...
    async def upload_binary(self, reservation: UploadReservation, data: bytes) -> None: ...
    async def get_image_status(self, image_urn: str) -> MediaStatus: ...
    async def create_image_post(self, command: ImagePostCommand) -> PublishReceipt: ...
    async def initialize_document(self, command: DocumentInitCommand) -> UploadReservation: ...
    async def get_document_status(self, document_urn: str) -> MediaStatus: ...
```

Also isolate `TokenVault`, `Clock` and `AssetStore`.

## 6. Commands

- `CreateEvidencePack`
- `CreateDraftVersion`
- `RecordQaResult`
- `ApproveDraft`
- `RejectDraft`
- `SchedulePublication`
- `CancelPublication`
- `ExecutePublication`
- `ResolveUncertainPublication`
- `StartLinkedInOAuth`
- `CompleteLinkedInOAuth`
- `RecordManualMetrics`

Each command validates current state, runs transactionally, emits audit/outbox events and returns a stable response.

## 7. Outbox

Changes that require Telegram notification create an `outbox_events` row in the same transaction. n8n sends and acknowledges later.

## 8. Concurrency

Acquire due jobs using `SELECT ... FOR UPDATE SKIP LOCKED` or equivalent.

Attempt phases:

```text
ACQUIRED
PREPARED
FINAL_REQUEST_STARTED
FINAL_RESPONSE_RECEIVED
COMPLETED
```

Recovery from `FINAL_REQUEST_STARTED` without response becomes `PUBLISH_UNCERTAIN`.

## 9. Time

- RFC3339 at API boundary;
- `timestamptz` UTC in DB;
- user timezone initially `Europe/Chisinau`;
- IANA timezone conversion.

## 10. Degradation

- n8n unavailable: state remains; workflow waits.
- LinkedIn unavailable: retry or uncertain state; content intact.
- Telegram unavailable: outbox retries; state remains.
- LLM unavailable: approved drafts still publish.

A future web UI must consume the same API and introduce no new domain rules.

## 11. Stage 0 exception

The feasibility harness is intentionally smaller than the production topology:

- one FastAPI process;
- in-memory one-time OAuth state;
- encrypted local connection file outside Git;
- owner-invoked text/image CLI;
- no PostgreSQL, n8n, Telegram, scheduler, LLM or outbox.

It is not a partial Stage 1 implementation. Outstanding states are lost on restart,
which is acceptable only for the single-owner spike. See ADR-009.

In production, n8n owns the timer trigger only. `publisher-api` owns due-job
acquisition, retry classification and all LinkedIn calls. See ADR-010.
