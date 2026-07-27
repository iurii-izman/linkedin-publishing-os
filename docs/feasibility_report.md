# Stage 0 LinkedIn Feasibility Report

**Status:** `GO`
**Allowed final gate:** `GO | GO_WITH_LIMITATIONS | NO_GO`  
**Owner execution date (UTC):** 2026-07-23T21:42:36.523Z

**Specification verification date:** 23 July 2026

The owner manually confirmed the sanitized live observations recorded below.

## Developer application

| Observation | Result | Sanitized evidence reference |
|---|---|---|
| OIDC product enabled | PASS | Owner-confirmed Developer Portal configuration |
| Share on LinkedIn enabled | PASS | Owner-confirmed Developer Portal configuration |
| Requested scopes | `openid profile w_member_social` | Stage 0 OAuth configuration |
| Granted scopes | PASS: `openid profile w_member_social` | Token verification |
| Exact HTTPS redirect accepted | PASS | Completed OAuth callback |

## OAuth and identity

| Observation | Result |
|---|---|
| OAuth | PASS |
| Token introspection | PASS: active token and matching client |
| Required scopes | PASS: `openid profile w_member_social` |
| OAuth state replay rejected | PASS: automated test |
| Token expiry observed | PASS |
| Encrypted token storage | PASS |
| Identity / UserInfo | PASS |
| Person URN available and accepted for publishing | PASS |
| Invalid/expired token behavior | NOT_RUN |

## Text post smoke

| Observation | Result |
|---|---|
| OAuth | PASS |
| Token introspection | PASS |
| Required scopes | PASS: `openid profile w_member_social` |
| Identity / UserInfo | PASS |
| Encrypted token storage | PASS |
| Exact payload approval and hash | PASS |
| Endpoint | PASS: `POST /rest/posts` |
| Version header | `202607` observed, configurable |
| HTTP 201 | PASS at `2026-07-23T21:42:36.523Z` |
| `x-restli-id` / post URN | `urn:li:share:7486173947814678528` |
| Manually visible on owner profile | PASS |
| Paragraphs, bullets and hashtags | PASS: owner verified |
| Duplicate retry | NO |
| Duplicate post observed | NO |
| Post retained after owner review | YES |
| Read verification | NOT_AVAILABLE |
| Sanitized and uncertain error behavior | PASS: automated tests |

## Image smoke

| Observation | Result |
|---|---|
| Exact caption and PNG checksum bound in a review fingerprint | PASS: local dry-run |
| PNG validation | PASS: 1200 x 1200, RGB, no transparency |
| `POST /rest/images?action=initializeUpload` | PASS: HTTP 200, one attempt |
| Binary upload | PASS: one raw-byte PUT |
| Upload HTTP 201 | PASS |
| Versioned image status GET | NOT_AVAILABLE_WITH_CURRENT_SCOPE |
| Fixed processing delay | PASS: bounded 8-second delay, no polling |
| Final `POST /rest/posts` | PASS |
| Final HTTP 201 | PASS: one attempt |
| Image post identifier received | PASS |
| Automatic ambiguous retry | NO |
| Manual profile verification | PASS: owner verified |
| Image visible without cropping | PASS |
| Card readability | PASS: title, cards, arrows and footer are visible |
| Caption visible | PASS; LinkedIn's “more” collapse is expected UI behavior |
| Alt text UI verification | NOT_AVAILABLE |
| Duplicate post observed | NO |
| Post retained after owner review | YES |

## Capability decision and limitations

- Text publication: `GO`
- Image publication: `GO`
- Overall Stage 0: `GO`
- Document publication: `DEFERRED`
- Analytics: `DEFERRED_RESTRICTED`
- Legacy `/v2/ugcPosts`: `NOT_SELECTED`; use only after an explicit documented
  owner decision if `/rest/posts` is clearly rejected before any final request.
- LinkedIn read verification for the created post is unavailable in Stage 0.
- Alt text cannot be independently verified through the current LinkedIn UI.
- Cloudflare Quick Tunnel is temporary Stage 0 infrastructure.
- Production PostgreSQL persistence and migrations are not implemented.
- Telegram approval, production n8n orchestration and scheduling are not implemented.
- Stage 1 has not started.

## Gate decision

`GO`

Rationale: owner-operated OAuth, token verification, identity lookup, exact-hash
approval and one text publication through `POST /rest/posts` passed. The owner
confirmed the post on the LinkedIn profile with correct paragraphs, bullets and
hashtags and no duplicate. The image initialize, binary upload and one final image
post request also passed. The owner confirmed that the image is visible without
cropping, the diagram remains readable, the caption is present and no duplicate was
created. The remaining infrastructure and read-verification limitations do not block
the Stage 0 feasibility decision.
