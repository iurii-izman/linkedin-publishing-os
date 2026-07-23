# LinkedIn Publishing OS — Master Specification

## 1. Product definition

LinkedIn Publishing OS is a single-user system that prepares, validates, approves, schedules and publishes professional posts to the owner's personal LinkedIn profile.

The product is not an autonomous social bot. It is a controlled publishing pipeline:

```text
source → evidence → draft → QA → human approval → schedule → publish → audit
```

The owner should spend time on judgment, professional positioning and conversations. The system should remove repetitive work: collecting ideas, connecting them with verifiable evidence, drafting, translation, quality checks, scheduling, media preparation, publication logging and optional analytics.

## 2. Product goal

Create a safe and maintainable system that can publish two high-quality LinkedIn posts per week with:

- minimal manual routine;
- explicit human approval;
- verifiable claims;
- no browser automation;
- no duplicate posts;
- clear operational status;
- recoverable failures;
- a development structure suitable for Codex.

## 3. Primary user

The initial system is designed for one owner:

- systems/business analyst with 6+ years of commercial CRM and integration experience;
- strong Bitrix24, 1C integration, REST API, BPMN and process automation background;
- applied AI/CRM portfolio projects;
- remote job-search positioning;
- Russian native, English B2;
- content should support Systems Analyst, Business Systems Analyst, CRM Analyst and Integration Analyst positioning.

Multi-user SaaS, organization pages and customer tenancy are explicitly out of scope.

## 4. Success criteria

### Product outcome

Within four weeks after Stage 1:

- a raw idea can become an approved scheduled draft without editing workflow internals;
- a due approved post is published exactly once under normal conditions;
- the system preserves the LinkedIn post URN and a full audit trail;
- an OAuth failure cannot lose a post;
- a modified draft cannot use an earlier approval;
- unsupported claims are blocked before approval;
- the owner receives Telegram status and actionable error messages.

### Operational target

- Two posts per week.
- At least 80% of generated drafts require only light editing.
- Zero duplicate publications caused by the system.
- Zero leaked tokens or private evidence.
- Zero browser automation.
- Recovery time from ordinary failures: under 15 minutes.
- Reauthorization does not require recreating scheduled jobs.

## 5. Non-goals

- editing the LinkedIn profile;
- connection automation;
- automated DMs;
- automatic reactions or comments;
- scraping profiles, feeds or analytics pages;
- engagement farming;
- multi-platform distribution in the initial release;
- team collaboration;
- customer accounts;
- billing;
- video generation;
- generalized internet RAG;
- autonomous posting without approval;
- claiming portfolio work as commercial production.

## 6. Architecture decision

```text
┌─────────────────────────────────────────────────────────┐
│ Sources                                                 │
│ Telegram notes · GitHub events · RSS · manual API       │
└───────────────────────┬─────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────┐
│ n8n orchestration                                      │
│ intake · scheduling · LLM calls · Telegram · alerts     │
└───────────────────────┬─────────────────────────────────┘
                        │ authenticated internal API
                        ▼
┌─────────────────────────────────────────────────────────┐
│ publisher-api (FastAPI)                                 │
│ domain state · OAuth · approval · assets · publish      │
│ LinkedIn adapter · audit · capability flags             │
└───────────────┬───────────────────────┬─────────────────┘
                │                       │
                ▼                       ▼
      ┌──────────────────┐    ┌─────────────────────────┐
      │ PostgreSQL       │    │ LinkedIn official APIs  │
      │ source of truth  │    │ OAuth · Posts · Media   │
      └──────────────────┘    └─────────────────────────┘
```

### Why not put all LinkedIn logic in n8n

Raw n8n HTTP nodes are acceptable for the Stage 0 feasibility spike. They are not the production boundary because:

- media publication has multiple steps and asynchronous states;
- OAuth lifecycle must not leak tokens;
- retry and ambiguous publish outcomes require code-level control;
- state transitions need database transactions;
- contracts should be testable without importing workflow JSON;
- API version migration should be isolated;
- Codex can maintain typed Python code more reliably than business logic spread over workflow nodes.

### Responsibility split

**publisher-api owns:** domain entities, state transitions, OAuth, encrypted tokens, author URN, API version, capabilities, media, publication, duplicate protection, audit and optional analytics.

**n8n owns:** source triggers, GitHub/RSS polling, LLM calls, Telegram, cron, notifications and stable command calls to publisher-api.

**PostgreSQL owns:** authoritative state, locks, uniqueness, job schedule and full history.

## 7. Stage 0 feasibility gate

No Stage 1 publication implementation begins until a real LinkedIn application proves:

1. Sign in with LinkedIn using OpenID Connect can be enabled.
2. Share on LinkedIn can be enabled.
3. OAuth returns `w_member_social`.
4. the member identifier can form a valid person URN;
5. one text post can be created;
6. the post ID/URN is captured;
7. image initialization/upload is attempted when the app permits it; an unavailable
   image capability is recorded and may produce `GO_WITH_LIMITATIONS`;
8. invalid/expired token behavior is observed;
9. the actual API path is documented:
   - preferred: `POST /rest/posts`;
   - legacy diagnostic only: `POST /v2/ugcPosts`, selected explicitly after a clear
     pre-send `/rest/posts` rejection and never as an automatic fallback;
10. current `Linkedin-Version` is confirmed.

A failed gate does not justify browser automation. It changes scope to draft preparation and manual LinkedIn scheduling.

## 8. Functional scope

### Content intake

Inputs:

- Telegram text note;
- Telegram URL;
- manual API request;
- selected GitHub release or repository event;
- selected RSS item.

Every source receives normalized text, canonical URL, source type, timestamp, content hash, trust level and visibility.

### Topic scoring

Each candidate receives 0–5 values for career relevance, practical usefulness, evidence strength, novelty, privacy risk, misinterpretation risk and duplication risk.

Reference formula:

```text
priority =
3 × career_relevance
+ 2 × practical_usefulness
+ 3 × evidence_strength
+ novelty
- 2 × privacy_risk
- 2 × misinterpretation_risk
- duplication_risk
```

The formula ranks. It does not authorize publication.

### Evidence pack

A draft may be generated only from a frozen evidence pack containing topic, source references, allowed claims, claim classes, forbidden inferences, uncertainty notes, language and audience.

Claim classes:

- `COMMERCIAL_VERIFIED`
- `PORTFOLIO_VERIFIED`
- `CERTIFICATE_VERIFIED`
- `PUBLIC_SOURCE_VERIFIED`
- `PERSONAL_OBSERVATION`
- `UNVERIFIED`

`UNVERIFIED` claims are excluded.

### Draft generation

Structured output contains language, audience, pillar, three hooks, selected hook, body, closing, full text, hashtags, visual brief, source IDs, used claim IDs and warnings.

A generator never publishes.

### QA gate

Deterministic rules plus a separate LLM reviewer.

Mandatory checks:

- claim IDs exist;
- no forbidden claims;
- commercial/portfolio wording is consistent;
- no private source is linked;
- no secrets or personal data;
- language is correct;
- length and link policy are respected;
- no repeated recent opening;
- no unsupported automation promise.

Results:

- `PASS`
- `PASS_WITH_WARNINGS`
- `FAIL`

Only `PASS` is ordinary MVP approval. Warning override is explicit and audited.

### Approval

Approval binds immutable fingerprints:

```text
text_hash = SHA256(normalized_final_text)
asset_checksum = SHA256(asset bytes) or null
approval_fingerprint = SHA256(text_hash + asset_checksum + language + visibility)
```

Any change invalidates approval.

### Scheduling and publication

A publication job requires approved draft, UTC schedule, profile, visibility, asset, fingerprint and valid capability.

The API:

1. locks the job transactionally;
2. revalidates approval;
3. checks token, version and asset;
4. records final request phase;
5. calls LinkedIn;
6. captures status and `x-restli-id`;
7. stores post URN;
8. emits audit/outbox.

### Media order

1. text;
2. single image;
3. PDF/document;
4. multi-image later;
5. video deferred.

### Analytics

Default mode is `manual`. API mode is enabled only if Community Management access and `r_member_postAnalytics` are granted.

## 9. Domain states

### Draft

```text
GENERATING → DRAFTED → QA_RUNNING
→ QA_FAILED | AWAITING_APPROVAL
→ APPROVED | REJECTED
→ INVALIDATED
```

### Asset

```text
CREATED → VALIDATED → UPLOAD_PENDING → UPLOADING
→ PROCESSING → AVAILABLE
→ UPLOAD_FAILED | PROCESSING_FAILED
```

### Publication job

```text
CREATED → SCHEDULED → PUBLISHING → PUBLISHED
```

Failure branches:

```text
AUTH_REQUIRED
RATE_LIMITED
VALIDATION_FAILED
ASSET_FAILED
PUBLISH_FAILED
PUBLISH_UNCERTAIN
CANCELLED
```

`PUBLISH_UNCERTAIN` requires a human check. It is not retried automatically.

## 10. Exactly-once boundary

LinkedIn does not document a general post idempotency key. The system guarantees exactly-once command execution internally under normal conditions, but not absolute exactly-once delivery across an ambiguous external network boundary.

Protection:

- unique publication fingerprint;
- database row lock;
- one active attempt;
- no duplicate active fingerprint;
- no automatic retry after final timeout;
- post URN stored immediately;
- ambiguous result routed to manual verification.

## 11. LinkedIn documentation baseline as of 23 July 2026

- open consumer product `Share on LinkedIn` grants `w_member_social`;
- member authorization uses 3-legged OAuth and a one-time application-generated
  `state` even though the LinkedIn parameter table labels it optional;
- documented access-token lifetime is 60 days, but code uses returned `expires_in`;
- preferred base path is `/rest/`;
- current official Marketing API version is `202607`;
- Posts API requires `Linkedin-Version` and `X-Restli-Protocol-Version: 2.0.0`;
- text, image, document and multi-image types are documented;
- member analytics requires additional `r_member_postAnalytics` access;
- `r_member_social` is restricted.

The API version is configuration, never a permanent constant. These are verified
documentation facts, not proof that the owner's application has the products,
author identity or endpoint behavior. Those remain Stage 0 observations.

## 12. Security model

Data classes:

- **Secret:** client secret, access token, encryption key.
- **Sensitive:** author URN, expiry, approvals.
- **Internal:** drafts, source notes, QA reports.
- **Public candidate:** approved text and media.
- **Public:** published URN and public URL.

Controls:

- encrypted tokens;
- HTTPS;
- OAuth `state`;
- no secrets in logs;
- Telegram allowlist;
- authenticated internal API;
- least-privilege DB;
- synthetic fixtures;
- encrypted backups;
- explicit retention.

## 13. Technology baseline

- Python 3.12+
- FastAPI
- Pydantic v2
- SQLAlchemy 2
- Alembic
- PostgreSQL 16+
- httpx
- pytest
- Ruff
- mypy
- structured logging
- maintained authenticated-encryption library
- self-hosted n8n
- Telegram bot
- OpenAI-compatible LLM
- Docker Compose

Redis, queue workers and Kubernetes are deferred.

## 14. Test strategy summary

- unit tests for transitions, claims and fingerprints;
- PostgreSQL integration tests;
- LinkedIn contract tests with mock server;
- migration up/down tests;
- security redaction tests;
- n8n contract tests;
- controlled owner-operated live smoke;
- explicit 401, 403, 409, 426, 429, 500, 503, timeout and malformed-response cases.

No automated test may publish to the real profile.

## 15. Delivery stages

### Stage 0 — feasibility

Prove official API path and record evidence.

### Stage 1 — reliable text publishing core

API, DB, OAuth, immutable drafts, approval, schedule, text publisher, audit, outbox, duplicate and uncertain protection.

### Stage 2 — n8n content pipeline

Source intake, evidence, structured generation, QA and Telegram approval.

### Stage 3 — media

Image and PDF/document.

### Stage 4 — intelligence

GitHub/RSS policies, similarity, pillar balance and weekly review.

### Stage 5 — optional analytics

Only after actual scope approval.

## 16. MVP release definition

MVP is complete when a Telegram idea can become an evidence-backed draft, pass QA, receive exact approval, be scheduled and published once, while preserving URN, audit, failure classification and OAuth recovery. Image publishing must work. PDF may be the next minor release.

## 17. Safe fallback

If official publishing access is unavailable:

```text
source → evidence → draft → QA → approval → scheduled reminder
```

The owner then uses LinkedIn's native scheduler manually. Missing API access is never replaced with prohibited automation.
