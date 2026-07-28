# Stage 1 Vertical MVP

## Status and scope

Stage 1 implements one production-oriented, immediate text flow:

```text
draft → immutable revision → exact approval → PREPARED
→ PUBLISHING → PUBLISHED | FAILED | PUBLISH_UNCERTAIN
```

PostgreSQL is authoritative. Stage 0 remains available as the isolated feasibility
harness and its ignored encrypted store is not deleted or modified. Telegram, n8n
production workflows, scheduling, generation, media, analytics and a web UI remain
outside this slice.

Live LinkedIn publishing is disabled by default and was not used to validate this
stage.

## Local setup

Copy `.env.example` to ignored `.env` and replace placeholders. Stage 1 requires:

- `DATABASE_URL`, `DATABASE_POOL_SIZE`, `DATABASE_MAX_OVERFLOW` and
  `DATABASE_CONNECT_TIMEOUT`;
- a dedicated `APP_OWNER_KEY` of at least 32 characters;
- `TOKEN_ENCRYPTION_KEY` and `STAGE1_TOKEN_KEY_ID`;
- `STALE_PUBLICATION_SECONDS`;
- `LINKEDIN_PUBLISHER_MODE=disabled`;
- `LIVE_LINKEDIN_PUBLISHING_ENABLED=false`.

The example Compose PostgreSQL port binds to `127.0.0.1` only. It creates separate
least-privilege `publisher` and `n8n` users/databases and keeps data in a named
volume.

```bash
uv sync --frozen --dev
docker compose -f docker-compose.example.yml up -d postgres
uv run alembic upgrade head
uv run lpos-stage1 database current
uv run uvicorn publisher_api.main:create_app --factory --no-access-log
```

The API never applies migrations at startup. `/health` checks only the process.
`/ready` returns 200 only when PostgreSQL is reachable and Alembic is at
`0001_stage1_vertical`.

## Exact text and approval

Revision text uses canonicalization `utf8-exact-v1`: the SHA-256 input is exactly
the UTF-8 bytes received by the server. There is no Unicode, whitespace or line-ending
normalization. Changing one space, character, or newline changes `text_sha256`.

Revisions are immutable rows and database triggers reject update/delete. Creating a
revision increments `revision_number`, links `supersedes_revision_id`, and makes the
new row current. Old approvals remain historical but cannot authorize publication.

The server calculates:

```text
revision_sha256 = SHA256(exact UTF-8 text)
approval_fingerprint = SHA256(canonical JSON of revision ID, hash and canonicalization version)
```

Only the current revision can be approved, prepared or executed. A revoked approval
is unusable.

## Owner authentication and idempotency

All Stage 1 reads and mutations require `X-Owner-Key`; comparisons are constant-time.
`/health` and `/ready` are public. The key is never placed in OpenAPI, responses,
logs or audit metadata.

`Idempotency-Key` (16–128 characters) is required for draft creation, revision
creation, approval, publication preparation and execution. PostgreSQL stores a
scope, key, request fingerprint and resource ID under a unique constraint.

- same key and same request returns the original resource;
- same key and changed request returns 409;
- publication destination `(revision_id, connection_id)` is unique;
- every publication has at most one `PublicationAttempt`, and its number must be 1.

Row locks serialize prepare/execute checks. A replay or concurrent execute observes
the existing `PUBLISHING` or terminal row and does not invoke the adapter again.

## Transaction and network boundary

Prepare performs database validation only and creates `PREPARED`.

Execute transaction A locks the aggregate, revalidates the current revision and
exact approval, transitions to `PUBLISHING`, creates attempt 1 and commits. The
single network call happens after that transaction. Transaction B locks the same
publication and records:

- exact 201 plus identifier as `PUBLISHED`;
- an unambiguous non-retryable 4xx as `FAILED`;
- timeout, connection reset, response loss or 5xx as `PUBLISH_UNCERTAIN`.

No transaction is held across the LinkedIn request. `PUBLISHED`, `FAILED` and
`PUBLISH_UNCERTAIN` are terminal in this slice. There is no force-retry or manual
retry command.

A token decryption failure is detected before the adapter is called and is persisted
as `FAILED` with `request_attempted=false`. An unexpected adapter exception, missing
identifier, or otherwise invalid final confirmation is conservatively persisted as
`PUBLISH_UNCERTAIN`; its raw exception text is not stored or logged.

If a process exits between transactions, a row remains `PUBLISHING`. Reconciliation
never calls LinkedIn:

```bash
uv run lpos-stage1 reconcile-stale-publications --dry-run
uv run lpos-stage1 reconcile-stale-publications --confirm
```

After the configured threshold, confirmation changes stale rows only to
`PUBLISH_UNCERTAIN`, completes the existing attempt and appends an audit event.

## Connection import and encryption

The explicit owner command reads the ignored Stage 0 connection:

```bash
uv run lpos-stage1 import-stage0-connection
uv run lpos-stage1 import-stage0-connection --confirm-import
```

The first form is a dry run. Confirmation decrypts the Stage 0 record only in
memory, validates expiry/scopes, and encrypts the plaintext under the Stage 1 AEAD
format:

```text
v1:<key-id>:<nonce-and-ciphertext>
```

Connection UUID and owner subject are authenticated associated data. The Stage 0
ciphertext is never copied into PostgreSQL, the Stage 0 file remains in place, and
the command prints only safe metadata. Repeating an import updates the one
owner-subject row.

## Safe operations

```bash
uv run lpos-stage1 database upgrade
uv run lpos-stage1 database current
uv run lpos-stage1 inspect-publication <uuid>
uv run lpos-stage1 export-safe-audit
```

Audit events are append-only at both the application and database levels. Safe audit
metadata excludes tokens, authorization values, encryption keys, signed URLs, post
text and LinkedIn request bodies.

## Backup, restore and rollback

Before migration or recovery, stop mutations and record the current revision:

```bash
uv run lpos-stage1 database current
docker compose -f docker-compose.example.yml exec -T postgres \
  pg_dump -U postgres -d publisher -Fc > publisher-stage1.dump
```

Encrypt and move backups off-host; never commit them. To verify a restore, use a
separate empty local database, restore the dump, run `alembic current`, `/ready` and
the offline E2E. Do not overwrite the only working database.

The Stage 0 rollback point is commit `95bc409f02e2ca18fa9c35d4789a0618829bf3c0`
and annotated tag `stage0-feasibility-go`. Rolling application code back does not
delete Stage 1 PostgreSQL data or `.stage0`. Use `alembic downgrade base` only after
a verified backup and only when discarding the Stage 1 schema is intentional.

## Controlled live validation checkpoint

Do not enable live mode as part of ordinary setup. A future owner-approved validation
requires all of the following:

1. one reviewed current revision and its exact approval fingerprint;
2. one fresh publication and idempotency key;
3. a valid imported connection;
4. `LINKEDIN_PUBLISHER_MODE=live`;
5. `LIVE_LINKEDIN_PUBLISHING_ENABLED=true`;
6. `confirm_execute=true`;
7. separate explicit owner authorization for that single post.

Stop before step 4 until that authorization is given. Any ambiguous result must
remain `PUBLISH_UNCERTAIN` and be checked manually; it is never retried.
