# Stage 2 Live Validation

## Validation record

- Validation date (UTC): `2026-07-29`
- Branch: `stage2-telegram-orchestration`
- Validated implementation commit: `a61f85a7bf67c84aa36adb786cf90068bed59131`
- Validation type: controlled, owner-approved Telegram-to-LinkedIn text publication

## Confirmed results

| Check | Result |
|---|---|
| PostgreSQL authoritative state | PASS |
| Immutable exact revision | PASS |
| Telegram preview messages created | 1 |
| Owner user/chat verification | PASS |
| Opaque one-time callback | PASS |
| Exact approval and fingerprint | PASS |
| n8n orchestration | PASS |
| Direct n8n-to-LinkedIn calls | 0 |
| Publication prepare | PASS |
| LinkedIn POST attempts | 1 |
| HTTP result | 201 |
| Final state | `PUBLISHED` |
| `PublicationAttempt` rows | 1 |
| Telegram result delivery | PASS |
| Audit trail | PASS |
| Manual LinkedIn verification | PASS |
| Duplicate publication | NO |
| Automatic LinkedIn retry | NO |
| Secrets exposed | NO |
| Live endpoint disabled after validation | YES |
| Telegram webhook disabled after validation | YES |
| Temporary tunnel stopped | YES |

The application persisted that a LinkedIn post identifier was received, without
retaining its value in this report. No access token, callback token, owner key,
service key, encryption key, full person URN, credential value or environment
content is recorded here.

## Owner verification

The owner manually confirmed that:

- Telegram displayed the final `PUBLISHED` result;
- the publication appeared in the LinkedIn profile;
- the exact paragraphs and bullet symbols were preserved;
- hashtags were recognized;
- only one publication was created.

## Operational observation

The first temporary Cloudflare Quick Tunnel ended before callback delivery.
Telegram reported HTTP 530, while PostgreSQL still showed no approval,
publication or LinkedIn attempt. A replacement temporary tunnel was created, the
expired approval request was replaced with a fresh one bound to the same immutable
revision, and the owner performed a new callback. This recovery caused no LinkedIn
retry and no duplicate publication.

The live run also exposed an n8n export compatibility issue: current n8n versions
require URL-safe production trigger names, and Telegram `replyMarkup` plus
`inlineKeyboard` must be top-level node parameters. The workflow exports and
offline contract tests were corrected after the observation.

## Scope and limitations

This validation proves the controlled immediate text path:

```text
Immutable Revision → Telegram exact preview → owner callback
→ persisted exact Approval → PREPARED → one LinkedIn POST
→ PUBLISHED → Telegram result delivery
```

It does not validate a permanent webhook deployment, scheduling, AI generation,
image publication or production operations. Account-less Cloudflare Quick Tunnels
have no uptime guarantee and remain unsuitable as persistent infrastructure.
LinkedIn live publishing, the Telegram webhook and both n8n workflows were disabled
after validation.
