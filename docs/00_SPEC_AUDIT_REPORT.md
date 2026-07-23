# Specification Audit Report

**Audit date:** 23 July 2026  
**Conclusion:** **READY_WITH_FIXES**  
**Stage 0 decision:** harness ready; real feasibility gate **NOT_RUN**

## 1. Executive conclusion

The original 43-file specification pack had a sound product boundary and a strong
uncertain-publication model, but it was not implementation-ready. The largest gaps
were an unimplemented safety spike, an unqualified OIDC-subject assumption, weak
referential design in the reference SQL, an unusable two-application PostgreSQL
example, and no repeatable artifact validation.

The high-risk internal issues identified below are corrected. Stage 0 can now be run
by the owner without a database, scheduler, LLM, Telegram or n8n production workflow.
No real LinkedIn access or post has been claimed.

## 2. Repository inventory

### Initial inventory

The repository contained 43 tracked files:

- 5 root specification/configuration files plus `.env.example`;
- 13 numbered detailed documents;
- 8 ADRs;
- 4 JSON event schemas;
- OpenAPI and PostgreSQL reference schemas;
- 2 content/evidence YAML files;
- 7 prompts;
- one Docker Compose example and one manifest.

There was no application code, test suite, dependency definition, lock file, CI,
manual Stage 0 guide, feasibility report, audit report or repository validator.

### Inventory checks

| Check | Initial result | Corrected result |
|---|---|---|
| README/manifest listed files exist | PASS | PASS |
| Manifest covers repository artifacts | FAIL: manifest omitted itself and all future implementation artifacts | Corrected manifest is validated by script |
| Internal Markdown links | PASS for initial pack | Validator added |
| JSON parse | PASS | Validator added |
| YAML parse | PASS | Validator added |
| JSON Schema metaschema | Not checked | Validator added |
| OpenAPI 3.1 validation | Structurally parseable; contract gaps below | Validator added and contract clarified |
| PostgreSQL plausibility | Parse-oriented reference only; structural weaknesses | Join tables and integrity checks added |
| Prompt/task IDs | Stage prompts align with task epics | Preserved |
| Prohibited automation dependency | No implementation existed | Explicit dependency validator; none introduced |

Generated VCS internals under `.git/` were inventoried but are not product artifacts.
Local caches, `.venv`, `.env` and encrypted `.stage0/` state are excluded by
`.gitignore`.

## 3. Confirmed strengths

- Official LinkedIn OAuth/API-only boundary is explicit.
- Networking, engagement farming, scraping and hidden UI automation are prohibited.
- Human approval is tied to immutable text and asset identity.
- PostgreSQL, FastAPI, n8n and Telegram ownership boundaries are directionally clear.
- `PUBLISH_UNCERTAIN` correctly rejects claims of distributed absolute exactly-once.
- Final post requests are not silently retried after ambiguous outcomes.
- Analytics is optional and gated on actual restricted access.
- Commercial experience and portfolio prototypes are modeled as different evidence
  classes.

## 4. Findings and corrections

### Critical

No critical finding remained after review. No credential was present and no existing
path could publish because there was no implementation.

### High

#### AUD-H-001 — Stage 0 had no executable safety boundary

- **Affected:** `TASKS.md`, `.env.example`, repository root
- **Risk:** the documents required a live spike but supplied no implementation,
  explicit live confirmation, encrypted local storage, redaction or timeout
  classification.
- **Why it matters:** an improvised smoke test could expose a token or duplicate a
  post.
- **Correction:** added a typed Stage 0 FastAPI/CLI harness, encrypted connection
  file, synthetic-content requirement, dry preparation and mandatory
  `--confirm-live-publish`.
- **Status:** **CORRECTED; real smoke remains owner-operated.**

#### AUD-H-002 — OIDC `sub` was treated too close to a proven author ID

- **Affected:** `MASTER_SPEC.md`, `docs/04_LINKEDIN_INTEGRATION.md`,
  `docs/12_RISKS_AND_SOURCES.md`
- **Risk:** OIDC documents define a pairwise subject, while publishing documents use
  a person URN. Official guidance points toward using member identity, but the actual
  app must prove that its returned subject is accepted.
- **Why it matters:** a structurally valid but rejected author URN causes 403 and
  blocks publication.
- **Correction:** the harness constructs a strictly validated candidate URN and marks
  it `requires_live_author_validation`; all completion documents retain this as a
  Stage 0 observation.
- **Status:** **CORRECTED AS AN ASSUMPTION; LIVE VALIDATION PENDING.**

#### AUD-H-003 — Reference SQL allowed dangling evidence relationships

- **Affected:** `specs/schema.sql`, `docs/03_DOMAIN_MODEL.md`
- **Risk:** UUID/text arrays represented pack sources, allowed claims and used claims,
  so PostgreSQL could not enforce foreign keys.
- **Why it matters:** an approved draft could cite deleted or nonexistent evidence.
- **Correction:** replaced relationship arrays with normalized join tables and added
  SHA-256 domains and publication integrity checks.
- **Status:** **CORRECTED IN REFERENCE SCHEMA; migrations remain Stage 1.**

#### AUD-H-004 — Docker example did not create isolated application databases

- **Affected:** `docker-compose.example.yml`, `.env.example`
- **Risk:** only a `publisher` database/user was created and n8n received no explicit
  PostgreSQL settings.
- **Why it matters:** deployment could silently use SQLite or share excessive DB
  privilege.
- **Correction:** added separate `publisher`/`n8n` roles and databases, explicit n8n
  DB configuration, a pinned n8n image and an initialization script.
- **Status:** **CORRECTED AS A TOPOLOGY EXAMPLE; production hardening is Stage 1+.**

#### AUD-H-005 — Candidate evidence asserted verification without bundled evidence

- **Affected:** `data/candidate_evidence_seed.yaml`, `docs/06_CONTENT_ENGINE.md`
- **Risk:** the referenced CV is not in the repository and external portfolio claims
  were not independently audited in this task.
- **Why it matters:** importing the seed as publishable evidence could create
  unsupported professional claims.
- **Correction:** the seed is now explicitly an owner-review candidate and content
  policy requires evidence verification before activation.
- **Status:** **CORRECTED; OWNER EVIDENCE REVIEW PENDING.**

### Medium

#### AUD-M-001 — Legacy endpoint status was ambiguous

- **Affected:** `MASTER_SPEC.md`, `docs/04_LINKEDIN_INTEGRATION.md`, `TASKS.md`
- **Risk:** the self-service Share guide still shows `/v2/ugcPosts`, while current
  Posts API documentation says `/rest/posts` replaces it.
- **Correction:** `/rest/posts` is the only harness path. Legacy is an explicit,
  owner-decided diagnostic fallback only after a clear pre-send rejection, never
  after an ambiguous final request.
- **Status:** **CORRECTED.**

#### AUD-M-002 — OpenAPI omitted workflow operations and a stable error model

- **Affected:** `specs/openapi.yaml`, `docs/05_N8N_WORKFLOWS.md`
- **Risk:** n8n referenced content-item creation that the API did not define; error
  response bodies and callback denial details were inconsistent.
- **Correction:** added content-item and safe error contracts, callback denial
  parameters, response schemas and idempotency guidance.
- **Status:** **CORRECTED AS A STAGE 1 TARGET CONTRACT.**

#### AUD-M-003 — Retry and scheduler ownership was implied, not explicit

- **Affected:** `docs/02_ARCHITECTURE.md`, `docs/05_N8N_WORKFLOWS.md`,
  `docs/adr/010-domain-relations-and-execution-ownership.md`
- **Risk:** n8n and API could both retry the same publication.
- **Correction:** n8n owns only the trigger; `publisher-api` owns acquisition,
  classification and retries. Final post creation is never auto-retried.
- **Status:** **CORRECTED.**

#### AUD-M-004 — n8n operating assumptions lacked current limitations

- **Affected:** `docs/05_N8N_WORKFLOWS.md`, `docs/07_SECURITY.md`,
  `docs/12_RISKS_AND_SOURCES.md`
- **Risk:** the built-in LinkedIn node is limited to post creation and is unsuitable
  as the production token/state boundary; binary/execution retention can persist
  sensitive workflow data.
- **Correction:** documented the limitation, Telegram callback support, fixed
  encryption key, pruning, audit, credential-stub/export risk and filesystem binary
  retention.
- **Status:** **CORRECTED; no n8n workflow was built.**

#### AUD-M-005 — Upload URL handling had no resolved retention decision

- **Affected:** `docs/04_LINKEDIN_INTEGRATION.md`, `docs/07_SECURITY.md`,
  `specs/schema.sql`
- **Risk:** signed upload URLs could leak through DB diagnostics or workflow events.
- **Correction:** ADR-010 requires temporary encryption, strict host validation and
  deletion after completion/expiry; the Stage 0 harness never persists the URL.
- **Status:** **CORRECTED.**

### Low

#### AUD-L-001 — Validation was manual and non-repeatable

- **Affected:** repository-wide
- **Correction:** added `scripts/validate_repository.py` for structured data,
  OpenAPI, JSON Schemas, links, manifest and prohibited dependencies.
- **Status:** **CORRECTED.**

#### AUD-L-002 — API date/version wording could be mistaken for live app proof

- **Affected:** `README.md`, `MASTER_SPEC.md`, `docs/04_LINKEDIN_INTEGRATION.md`
- **Correction:** separated official documentation verification from real
  Developer Portal capability evidence.
- **Status:** **CORRECTED.**

## 5. External verification

All sources were accessed on **23 July 2026**.

| Fact | Official source | Verified result | Stage 0 confirmation |
|---|---|---|---|
| Open consumer products/scopes | [Getting Access](https://learn.microsoft.com/en-us/linkedin/shared/authentication/getting-access) | OIDC profile access and Share on LinkedIn `w_member_social` are listed as open permissions | Confirm product availability in actual portal |
| OIDC identity | [OIDC Sign In](https://learn.microsoft.com/en-us/linkedin/consumer/integrations/self-serve/sign-in-with-linkedin-v2) | `openid profile`; UserInfo is `/v2/userinfo`; `sub` is pairwise | Confirm author-URN acceptance |
| OAuth flow | [3-legged OAuth](https://learn.microsoft.com/en-us/linkedin/shared/authentication/authorization-code-flow) | Exact redirect, authorization code, state check, token `expires_in`; 60-day current issue; programmatic refresh limited | Observe fields/lifetime; no refresh assumed |
| Share access | [Share on LinkedIn](https://learn.microsoft.com/en-us/linkedin/consumer/integrations/self-serve/share-on-linkedin) | `w_member_social`; guide still documents `/v2/ugcPosts` | Do not select legacy unless needed |
| Current Posts API | [Posts API](https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/posts-api?view=li-lms-2026-06) | `/rest/posts` replaces ugcPosts; required version/Rest.li headers; 201 and `x-restli-id` | Real personal-member request |
| Current version | [Versioning](https://learn.microsoft.com/en-us/linkedin/marketing/versioning?view=li-lms-2026-07) | July 2026 is `202607`; monthly versions and no default version | Confirm endpoint accepts configured version |
| Image flow/status | [Images API](https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/images-api?view=li-lms-2026-02) | initialize upload, signed URL, image URN, `WAITING_UPLOAD`/`PROCESSING`/`AVAILABLE`/failure, final post | Real image smoke |
| Document flow | [Documents API](https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/documents-api?view=li-lms-2026-02) | initialize/upload/status; 100 MB/300-page documented ceiling | Deferred |
| Member analytics | [Member Post Statistics](https://learn.microsoft.com/en-us/linkedin/marketing/community-management/members/post-statistics?view=li-lms-2026-02) and [Increasing Access](https://learn.microsoft.com/en-us/linkedin/marketing/increasing-access?view=li-lms-2026-06) | `r_member_postAnalytics`; Community Management access; not an MVP assumption | Deferred/restricted |
| n8n Telegram callbacks | [Telegram node](https://docs.n8n.io/integrations/builtin/app-nodes/n8n-nodes-base.telegram/) | callback query answer operation is supported | Stage 2 |
| n8n security audit | [Security audit](https://docs.n8n.io/hosting/securing/security-audit/) | `n8n audit` reports credential, DB, filesystem, node and instance risks | Stage 2/production |
| n8n binary storage | [External storage](https://docs.n8n.io/hosting/scaling/external-storage/) | filesystem is viable; S3 external storage is enterprise and needs lifecycle pruning | Stage 3 |

Rate limits are application/member specific and must be read in the Developer Portal;
no universal quota is assumed. `429` and `Retry-After` are handled as observations.

## 6. Corrected architecture summary

```text
owner browser
  → Stage 0 FastAPI OAuth callback
  → encrypted local connection file
  → owner-invoked dry plan
  → explicit one-shot text/image CLI
  → official LinkedIn endpoints only
```

Stage 0 has no scheduler, PostgreSQL, n8n production workflow, Telegram, LLM,
document/video support or analytics.

After owner-approved Stage 0 GO only:

```text
n8n trigger/orchestration
  → authenticated publisher-api command
  → transactional PostgreSQL state/lock/attempt
  → official LinkedIn adapter
  → audit/outbox
```

## 7. Remaining assumptions

1. The owner's Developer Portal permits both required products and exact scopes.
2. OIDC `sub` is accepted as the person identifier for this app's author URN.
3. `/rest/posts` accepts personal member posts for the actual self-service app.
4. `202607` is accepted for Posts and Images by the actual app.
5. Image initialization/upload/status works for the member owner.
6. HTTP 201 includes a usable `x-restli-id`.
7. Candidate professional evidence is reviewed against source material outside this
   repository.

## 8. Stage 0 readiness

**READY FOR OWNER-OPERATED STAGE 0, NOT READY FOR STAGE 1.**

The mock harness and safety controls are implementation-ready. The gate remains
`NOT_RUN`; Stage 1 is prohibited until the owner records `GO` or
`GO_WITH_LIMITATIONS` in `docs/feasibility_report.md`.

