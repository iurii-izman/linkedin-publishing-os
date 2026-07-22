# n8n Workflow Contracts

## 1. Principle

n8n coordinates systems. It does not implement domain transitions or LinkedIn payloads.

Every workflow propagates:

```text
correlation_id
source_event_id
workflow_name
workflow_version
```

Every workflow has explicit error paths, safe bounded retries, Telegram operator notification and no secret echo.

## 2. WF-001 Telegram Content Intake

```text
Telegram Trigger
→ verify chat/user allowlist
→ parse note or URL
→ normalize
→ POST /v1/sources
→ POST /v1/content-items
→ acknowledge
```

Reject unknown users, empty ideas, detected secrets and unsupported files.

## 3. WF-002 GitHub Source Intake

Allowlisted repositories only.

Eligible:

- release;
- completed feature;
- architecture decision;
- validated integration;
- post-mortem;
- practical runbook.

Reject routine dependency updates, formatting commits, private content not approved as public-safe and indiscriminate commit feeds.

## 4. WF-003 RSS Intake

RSS is discovery, not owner evidence.

```text
Schedule → read allowlisted feeds → normalize → deduplicate
→ preliminary score → create candidate above threshold
```

## 5. WF-010 Evidence Builder

```text
GET content item
→ GET evidence policy
→ select relevant claim IDs
→ LLM structured suggestion
→ deterministic validation
→ POST immutable evidence pack
```

LLM may select evidence; it may not create verified claims.

## 6. WF-011 Draft Generator

```text
GET evidence pack
→ call LLM with JSON schema
→ validate
→ one repair attempt if schema invalid
→ POST draft version
→ request QA
```

## 7. WF-012 QA

```text
GET draft and evidence
→ deterministic QA
→ stop on hard fail
→ LLM reviewer
→ POST result
→ if PASS, send approval preview
```

## 8. WF-020 Telegram Approval

Preview shows topic, pillar, language, format, schedule, QA, warnings, exact text and media.

Buttons:

- Approve
- Edit
- Regenerate
- Change asset
- Schedule
- Reject

Callback data uses opaque IDs. Answer callback immediately, then call publisher-api. Replayed callbacks are idempotent.

## 9. WF-030 Scheduler

Every five minutes:

```text
Schedule Trigger
→ POST /v1/publication-jobs/execute-due?limit=N
→ process summaries/outbox
```

No direct LinkedIn call.

## 10. WF-031 Outbox Dispatcher

Fetch available events, send Telegram template, acknowledge only after success.

Events include draft ready, QA failed, approval invalidated, published, auth expiring/required, failed, uncertain, rate-limited and asset failed.

## 11. WF-032 OAuth Watchdog

Daily integration status. Notify only on expiring, required, revoked or misconfigured.

The production LinkedIn token must not remain in n8n after Stage 0.

## 12. WF-040 Weekly Review

Default manual analytics:

```text
Sunday → published posts → Telegram metric form
→ parse response → store snapshots → editorial summary
```

Career outcomes matter more than raw engagement.

## 13. Workflow versioning

Store exports under `n8n/workflows/` and a `workflow_manifest.yaml`.

- no credentials;
- readable node names;
- shared sub-workflows;
- export after production changes;
- review diffs;
- no direct production LinkedIn endpoint.

## 14. Workflow acceptance

Test happy path, replay, malformed input, API outage, unauthorized chat, duplicate callback, LLM rate limit, Telegram outage and secret redaction.
