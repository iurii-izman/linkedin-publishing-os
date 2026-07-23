# Domain Model and State Machines

## 1. Core entities

- **Source:** immutable captured input with type, canonical URL, body, hash, trust and visibility.
- **ContentItem:** editorial candidate with topic, pillar, scores and risks.
- **EvidenceItem:** reusable verified claim with class, source, allowed wording and forbidden inferences.
- **EvidencePack:** frozen set of evidence for one draft family.
- **DraftVersion:** immutable generated or edited version.
- **QaRun:** deterministic and LLM results stored separately.
- **Approval:** immutable decision for one draft version and asset state.
- **Asset:** media with checksum, storage reference, status and external URN.
- **PublicationJob:** scheduled intent.
- **PublicationAttempt:** execution attempt with phase and safe diagnostics.
- **LinkedInIntegration:** author identity, encrypted token, expiry, version and capabilities.
- **AuditEvent:** append-only event.
- **OutboxEvent:** reliable notification.

## 2. Invariants

1. Draft versions never mutate.
2. Approval references exactly one version.
3. Approval fingerprint includes asset checksum.
4. A job cannot be scheduled without approval.
5. Only one active job may exist for a publication fingerprint.
6. Published jobs have a LinkedIn post URN.
7. `PUBLISH_UNCERTAIN` is not automatically executable.
8. Tokens are never returned by application APIs.
9. `UNVERIFIED` claims cannot appear in approved drafts.
10. `PORTFOLIO_VERIFIED` cannot render as commercial production.
11. LLM QA cannot override deterministic hard failure.
12. Timestamps are UTC.
13. State transitions are audited.
14. A final attempt has at most one recorded final request start.

## 3. Draft transitions

| From | Command | To | Condition |
|---|---|---|---|
| `GENERATING` | success | `DRAFTED` | schema valid |
| `GENERATING` | failure | `GENERATION_FAILED` | error stored |
| `DRAFTED` | start QA | `QA_RUNNING` | evidence active |
| `QA_RUNNING` | pass | `AWAITING_APPROVAL` | deterministic pass |
| `QA_RUNNING` | fail | `QA_FAILED` | report stored |
| `AWAITING_APPROVAL` | approve | `APPROVED` | fingerprint created |
| `AWAITING_APPROVAL` | reject | `REJECTED` | decision stored |
| `APPROVED` | changed version/asset | `INVALIDATED` | history retained |

## 4. Publication transitions

| From | Event | To | Retry |
|---|---|---|---|
| `CREATED` | schedule | `SCHEDULED` | n/a |
| `SCHEDULED` | lock | `PUBLISHING` | n/a |
| `PUBLISHING` | 201 + URN | `PUBLISHED` | no |
| `PUBLISHING` | invalid token | `AUTH_REQUIRED` | after reauth |
| `PUBLISHING` | validation error | `VALIDATION_FAILED` | no |
| `PUBLISHING` | asset unavailable | `ASSET_FAILED` | after fix |
| `PUBLISHING` | 429 | `RATE_LIMITED` | backoff |
| `PUBLISHING` | network ambiguity | `PUBLISH_UNCERTAIN` | never automatic |
| `PUBLISHING` | clear pre-send failure | `PUBLISH_FAILED` | policy-based |

## 5. Publication fingerprint

```json
{
  "profile_id": "single-owner",
  "draft_version_id": "uuid",
  "text_hash": "sha256",
  "asset_checksum": "sha256-or-null",
  "language": "en",
  "visibility": "PUBLIC"
}
```

Schedule time is not part of content identity.

## 6. Audit events

Examples:

- `source.created`
- `evidence_pack.created`
- `draft.generated`
- `qa.completed`
- `draft.approved`
- `approval.invalidated`
- `publication.scheduled`
- `publication.locked`
- `linkedin.final_request_started`
- `publication.published`
- `publication.uncertain`
- `oauth.completed`
- `oauth.auth_required`
- `asset.available`
- `metrics.recorded`

## 7. Initial retention

- published drafts/audits: indefinite;
- rejected drafts: 180 days;
- raw public source bodies: 90 days;
- private source bodies: 30 days by default;
- OAuth sessions: 24 hours;
- safe attempt diagnostics: 180 days;
- temporary upload URLs: remove after completion;
- generated previews: 30 days unless published.

## 8. Relational integrity

Evidence-pack/source/claim and draft/claim membership uses normalized join tables.
UUID arrays are not used for domain relationships because PostgreSQL cannot enforce
element-level foreign keys on them. Draft versions and packs remain immutable after
creation.

The reference schema enforces that `PUBLISHED` has both post URN and timestamp and
that a job has at most one incomplete attempt. Application commands must additionally
enforce approved-draft scheduling and transition legality transactionally; reference
DDL is not a substitute for Stage 1 migration and repository tests.
