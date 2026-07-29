# Delivery Backlog

Status: `[ ]` not started · `[-]` in progress · `[x]` complete · `[!]` blocked · `[~]` deferred

## Stage 1 Vertical MVP checkpoint

- [x] PostgreSQL/Alembic foundation with upgrade, downgrade and repeat upgrade.
- [x] Draft plus immutable exact-UTF-8 revisions and server-side SHA-256.
- [x] Exact current-revision approval, revocation and DB-backed idempotency.
- [x] Immediate text prepare/execute with one-attempt constraint and row locks.
- [x] Ambiguous final outcomes and stale `PUBLISHING` reconcile to `PUBLISH_UNCERTAIN`.
- [x] Versioned AEAD connection import retaining the Stage 0 store.
- [x] Owner-authenticated API, append-only audit, offline fake-adapter E2E.
- [x] Controlled owner-approved live text publication: one attempt, HTTP 201,
  persisted `PUBLISHED`, idempotent replay with no additional LinkedIn call, and
  successful manual profile verification.

**Vertical slice status:** complete. Live LinkedIn publication remains disabled by
default after validation.

## Stage 2 Telegram orchestration checkpoint

- [x] PostgreSQL external approval request lifecycle and delivery metadata.
- [x] Opaque one-time callback token stored only as SHA-256.
- [x] Exact current-revision binding, expiry, invalidation and decision replay.
- [x] Independent FastAPI verification of Telegram owner user and chat IDs.
- [x] Dedicated n8n service authentication, distinct from owner authentication.
- [x] Sanitized send/decision workflow exports with no LinkedIn boundary access.
- [x] Offline approve, reject, expiry, stale-revision and lost-response E2E.
- [x] Controlled real Telegram validation with one message, one accepted owner
  callback, one LinkedIn attempt, HTTP 201, persisted `PUBLISHED` result and
  successful manual profile verification.

**Stage 2 status:** controlled vertical slice complete. LinkedIn live mode,
Telegram webhook and n8n workflows remain disabled after validation.

## EPIC 0 — LinkedIn API feasibility gate

### Stage 0 preparation (repository work)

- [x] Audit specification pack and current official documentation.
- [x] Add isolated FastAPI OAuth callback and encrypted local connection store.
- [x] Add dry request preparation and explicit live-publish confirmation.
- [x] Add mocked text/image/error/timeout/redaction tests.
- [x] Add owner manual-action guide and feasibility report template.
- [ ] Owner executes real Developer Portal/OAuth/post observations.

### LPOS-001 Developer application and products

- [ ] Create LinkedIn developer application.
- [ ] Enable OpenID Connect.
- [ ] Enable Share on LinkedIn.
- [ ] Configure exact HTTPS redirect URI.
- [ ] Record available scopes and current API version without secrets.

**Acceptance:** products visible, redirect URI accepted, no secret committed.

### LPOS-002 OAuth smoke

- [x] Implement temporary callback.
- [ ] Request `openid profile w_member_social`.
- [x] Validate one-time `state` in code and mock tests.
- [x] Implement authorization-code exchange.
- [ ] Record real `expires_in`.
- [x] Implement UserInfo retrieval.
- [ ] Validate the real author person URN.
- [ ] Record 401 behavior.

### LPOS-003 Text post smoke

- [x] Implement dry request and guarded one-shot `/rest/posts` command.
- [ ] Test `POST /rest/posts` with configurable version.
- [ ] Capture HTTP status and `x-restli-id`.
- [ ] Verify post manually.
- [ ] Record sanitized request/response.
- [ ] If unavailable, test documented legacy `/v2/ugcPosts`.

### LPOS-004 Image smoke

- [x] Implement guarded initialize/upload/status/post path with synthetic fixtures.
- [ ] Initialize image upload.
- [ ] Upload synthetic image.
- [ ] Create image post.
- [ ] Capture post URN.
- [ ] Document constraints.

### LPOS-005 Gate decision

- [x] Create `docs/feasibility_report.md` template.
- [ ] Mark `GO`, `GO_WITH_LIMITATIONS` or `NO_GO`.
- [ ] Do not proceed on `NO_GO`.

## EPIC 1 — Foundation

- [ ] LPOS-101 Scaffold FastAPI, settings, health, Ruff, mypy, pytest, Docker and CI.
- [ ] LPOS-102 Configure SQLAlchemy, Alembic, PostgreSQL, constraints and migration tests.
- [ ] LPOS-103 Add authenticated n8n-to-API service boundary and key-rotation runbook.

## EPIC 2 — OAuth and capabilities

- [ ] LPOS-201 OAuth start/callback, encrypted token, expiry, author URN and no token leakage.
- [ ] LPOS-202 Integration states: connected, expiring, auth required, revoked, misconfigured.
- [ ] LPOS-203 Capability flags for text, image, document and analytics.

## EPIC 3 — Evidence, drafts and approval

- [ ] LPOS-301 Evidence items, packs, classes, sources and seed import.
- [ ] LPOS-302 Immutable draft versions and hashes.
- [ ] LPOS-303 Deterministic QA plus structured LLM QA.
- [ ] LPOS-304 Approval fingerprint, reject, invalidation and callback idempotency.

## EPIC 4 — Scheduling and text publishing

- [ ] LPOS-401 Publication jobs, UTC schedule, cancellation and unique fingerprint.
- [ ] LPOS-402 Transactional job lock, one active attempt and stale-lock policy.
- [ ] LPOS-403 Typed LinkedIn text adapter, headers, version, URN and error taxonomy.
- [ ] LPOS-404 Ambiguous final result → `PUBLISH_UNCERTAIN`, no blind retry.
- [ ] LPOS-405 Transactional notification outbox.

## EPIC 5 — n8n orchestration

- [ ] LPOS-501 Telegram, GitHub and RSS source intake.
- [ ] LPOS-502 Evidence and structured generation workflow.
- [ ] LPOS-503 Telegram preview and approve/reject/edit/regenerate/schedule callbacks.
- [ ] LPOS-504 Due-job scheduler calling API only.
- [ ] LPOS-505 OAuth watchdog.

## EPIC 6 — Media

- [ ] LPOS-601 Asset storage, MIME/size validation, checksum and retention.
- [ ] LPOS-602 Images API, alt text and image post.
- [ ] LPOS-603 Documents API, bounded polling and PDF post.
- [~] LPOS-604 Multi-image after image/document stability.

## EPIC 7 — Analytics

- [ ] LPOS-701 Manual metric snapshots and weekly review.
- [~] LPOS-702 API analytics only if `r_member_postAnalytics` is approved.

## EPIC 8 — Security and operations

- [ ] LPOS-801 Secret management, encryption and redaction tests.
- [ ] LPOS-802 Backups and restore test.
- [ ] LPOS-803 Structured logs, metrics, health and alerts.
- [ ] LPOS-804 n8n audit, dependency, secret and container scans.

## EPIC 9 — Release

- [ ] LPOS-901 End-to-end acceptance: idea → approval → text/image publication.
- [ ] LPOS-902 MVP tag, release notes, runbook, limitations and rollback.
