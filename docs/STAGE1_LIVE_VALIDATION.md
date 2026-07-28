# Stage 1 Live Validation

## Validation record

- Validation date (UTC): `2026-07-28`
- Branch: `stage1-vertical-mvp`
- Validated commit: `19013f9dbf6691a8de72d225fe26648488642155`
- Validation type: controlled, owner-approved Stage 1 text publication

## Confirmed results

| Check | Result |
|---|---|
| PostgreSQL persistence | PASS |
| Stage 0 connection import | PASS |
| Immutable revision | PASS |
| Exact approval | PASS |
| Publication prepare | PASS |
| LinkedIn POST attempts | 1 |
| HTTP result | 201 |
| Final state | `PUBLISHED` |
| `PublicationAttempt` rows | 1 |
| Idempotent execute replay | PASS |
| Additional LinkedIn calls after replay | 0 |
| Audit trail | PASS |
| Manual LinkedIn verification | PASS |
| Automatic retry | NO |
| Secrets exposed | NO |
| Live mode disabled after validation | YES |

The application persisted the successful publication result and the fact that a
LinkedIn post identifier was received. This report intentionally does not retain
the identifier value, the full person URN, credentials, tokens, encryption keys or
local environment values.

## Owner verification

The owner manually confirmed that:

- the publication appeared in the LinkedIn profile;
- it was created exactly once;
- paragraphs and bullet symbols were preserved;
- hashtags were recognized;
- no duplicate was present;
- the post did not need to be deleted.

## Scope and limitations

This validation proves the controlled Stage 1 immediate text path:

```text
Draft → immutable Revision → exact Approval → PREPARED
→ one LinkedIn POST → PUBLISHED → persisted audit trail
```

It does not validate Telegram approval, n8n orchestration, scheduling, AI
generation or another Stage 1 slice. Live publishing remains disabled by default
and was disabled again after this validation.
