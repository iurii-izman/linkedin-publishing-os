# Stage 0 LinkedIn Feasibility Report

**Status:** `NOT_RUN`  
**Allowed final gate:** `GO | GO_WITH_LIMITATIONS | NO_GO`  
**Owner execution date (UTC):** _pending_  
**Specification verification date:** 23 July 2026

No live LinkedIn claim in this report is complete until the owner records sanitized
evidence from the real Developer Portal and profile.

## Developer application

| Observation | Result | Sanitized evidence reference |
|---|---|---|
| OIDC product enabled | PENDING | |
| Share on LinkedIn enabled | PENDING | |
| Requested scopes | `openid profile w_member_social` | |
| Granted scopes | PENDING | |
| Exact HTTPS redirect accepted | PENDING | |

## OAuth and identity

| Observation | Result |
|---|---|
| OAuth state replay rejected | Confirmed by automated mock test |
| Observed `expires_in` | PENDING |
| Refresh token returned | PENDING; not required or assumed |
| UserInfo `sub` observed | PENDING; record only sanitized shape |
| `urn:li:person:{sub}` accepted for publishing | PENDING |
| Invalid/expired token behavior | PENDING |

## Text post smoke

| Observation | Result |
|---|---|
| Endpoint | `POST /rest/posts` planned |
| Version header | `202607` planned, configurable |
| HTTP status | PENDING |
| `x-restli-id` / post URN | PENDING |
| Manually visible on owner profile | PENDING |
| Sanitized error behavior | PENDING |

## Image smoke

| Observation | Result |
|---|---|
| `POST /rest/images?action=initializeUpload` | PENDING |
| Upload accepted | PENDING |
| Image status reached `AVAILABLE` | PENDING |
| Image post HTTP status and URN | PENDING |
| Manually visible on owner profile | PENDING |

## Capability decision

- Text publication: `UNVERIFIED`
- Image publication: `UNVERIFIED`
- Document publication: `DEFERRED`
- Analytics: `DEFERRED_RESTRICTED`
- Legacy `/v2/ugcPosts`: `NOT_SELECTED`; use only after an explicit documented
  owner decision if `/rest/posts` is clearly rejected before any final request.

## Gate decision

`NOT_RUN`

Rationale: real owner-operated OAuth and smoke publication have not occurred. Only
the owner may change this to `GO`, `GO_WITH_LIMITATIONS` or `NO_GO`.

