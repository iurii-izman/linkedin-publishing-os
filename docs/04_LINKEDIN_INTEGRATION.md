# LinkedIn Integration Specification

## 1. Status

Expected baseline as of **23 July 2026**. Stage 0 must replace expectations with observed facts for the actual application.

## 2. Products and permissions

Required open products:

- Sign in with LinkedIn using OpenID Connect
- Share on LinkedIn

Expected scopes:

```text
openid
profile
w_member_social
```

Do not request `email` without a product need.

Optional restricted capability:

```text
r_member_postAnalytics
```

This depends on Community Management approval and is not assumed.

## 3. OAuth

Use member 3-legged authorization code flow.

Controls:

- exact redirect URI;
- random one-time `state`;
- server-side state with expiry;
- HTTPS;
- backend token exchange;
- client secret backend-only;
- encrypted token at rest;
- token never returned to n8n.

Use returned `expires_in`. Official docs currently state 60 days, but code must not hard-code it.

Reauthorize 14 days before expiry by default. Do not assume a refresh token. On 401, mark `AUTH_REQUIRED` and preserve jobs.

## 4. Member identity

OIDC UserInfo returns a pairwise `sub`. Stage 0 must verify the identifier accepted by:

```text
urn:li:person:{person_id}
```

Person IDs are application-specific.

## 5. Versioning

Preferred base:

```text
https://api.linkedin.com/rest/
```

Headers:

```http
Authorization: Bearer <token>
Linkedin-Version: 202607
X-Restli-Protocol-Version: 2.0.0
Content-Type: application/json
```

`202607` is the latest observed official version on 23 July 2026. It is configuration.

## 6. Text post

Preferred request:

```http
POST /rest/posts
```

Conceptual body:

```json
{
  "author": "urn:li:person:PERSON_ID",
  "commentary": "Final approved text",
  "visibility": "PUBLIC",
  "distribution": {
    "feedDistribution": "MAIN_FEED",
    "targetEntities": [],
    "thirdPartyDistributionChannels": []
  },
  "lifecycleState": "PUBLISHED",
  "isReshareDisabledByAuthor": false
}
```

Success is HTTP `201` with post ID in `x-restli-id`. A 201 without usable ID is an anomaly.

## 7. Legacy fallback

The self-service guide also documents:

```http
POST /v2/ugcPosts
```

Selection rule:

1. test `/rest/posts`;
2. use it when accepted;
3. use legacy only as a documented temporary fallback;
4. never run both paths for one job;
5. no fallback after an ambiguous final request.

## 8. Image flow

1. validate MIME/size;
2. calculate SHA-256;
3. `POST /rest/images?action=initializeUpload`;
4. store image URN and temporary upload URL;
5. upload binary;
6. confirm observed readiness;
7. create final post with image URN;
8. store post URN;
9. remove upload URL from logs.

Alt text is generated and reviewable.

## 9. Document flow

1. initially accept PDF;
2. validate MIME, extension, size, structure and checksum;
3. `POST /rest/documents?action=initializeUpload`;
4. upload;
5. bounded polling: `WAITING_UPLOAD`, `PROCESSING`, `AVAILABLE`, `PROCESSING_FAILED`;
6. publish only after `AVAILABLE`;
7. store document URN and checksum.

## 10. Analytics

Optional endpoint:

```http
GET /rest/memberCreatorPostAnalytics
```

Requires `r_member_postAnalytics`, not merely `w_member_social`.

Potential metrics include impressions, reach, reshares, reactions, comments, saves, sends, link clicks, followers gained and profile views from content.

## 11. Error taxonomy

- `400/422` → validation failure, no retry.
- `401` → auth required; preserve job.
- `403` → permission/product/URN problem; no blind retry.
- `404` → verify resource and endpoint.
- `409` → retry only under proven safe semantics.
- `426` → unsupported version; block publishing until migration.
- `429` → honor `Retry-After` or jittered backoff.
- `500/503` → bounded retry for media operations; final post may be uncertain.
- final network timeout after request starts → `PUBLISH_UNCERTAIN`.

## 12. Logging

Allowed: correlation ID, endpoint class, version, status, latency, safe code, post/media URN.

Forbidden: token, client secret, auth code, full upload URL, private source body, low-level full post text.

## 13. Feasibility report

Create `docs/feasibility_report.md` with enabled products, granted scopes, observed token lifetime, author URN method, selected endpoint/version, sanitized requests/responses, blockers and GO decision.
