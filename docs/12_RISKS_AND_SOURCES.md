# Risks, Assumptions and Source Registry

## 1. Risk register

| ID | Risk | Impact | Mitigation |
|---|---|---:|---|
| R-01 | Share product unavailable | Critical | Stage 0; manual scheduler fallback |
| R-02 | `/rest/posts` differs from docs | High | live spike; isolated adapter |
| R-03 | token expires/revoked | High | watchdog, encrypted expiry, reauth |
| R-04 | final response lost | Critical | uncertain state, no blind retry |
| R-05 | concurrent scheduler | High | DB lock and unique fingerprint |
| R-06 | LLM fabricates experience | Critical | claim IDs, deterministic QA, approval |
| R-07 | portfolio appears commercial | High | typed evidence and render rules |
| R-08 | private data leaks | Critical | visibility, scanning and preview |
| R-09 | API version sunset | High | configurable version and monthly review |
| R-10 | analytics scope unavailable | Medium | manual default |
| R-11 | too much logic in n8n | Medium | FastAPI boundary |
| R-12 | secrets in logs/export | Critical | redaction tests and secret scanning |
| R-13 | media processing stuck | Medium | bounded polling and operator state |
| R-14 | source prompt injection | High | source-as-data and claim allowlist |
| R-15 | Telegram misuse | High | allowlist and replay protection |

## 2. Assumptions to verify

- Share on LinkedIn is enabled for the actual app.
- member identifier forms an accepted author URN.
- `/rest/posts` accepts personal author with open scope.
- image initialization works with the app.
- `x-restli-id` is returned.
- version `202607` is supported by selected endpoints.
- no refresh token is assumed.
- analytics access is not assumed.

## 3. Official source registry

### Access and OAuth

- https://learn.microsoft.com/en-us/linkedin/shared/authentication/getting-access
- https://learn.microsoft.com/en-us/linkedin/shared/authentication/authentication
- https://learn.microsoft.com/en-us/linkedin/shared/authentication/authorization-code-flow-native
- https://learn.microsoft.com/en-us/linkedin/consumer/integrations/self-serve/sign-in-with-linkedin-v2
- https://learn.microsoft.com/en-us/linkedin/consumer/integrations/self-serve/share-on-linkedin

### Publishing

- https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/posts-api
- https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/images-api
- https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/documents-api
- https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/multiimage-post-api

### Operations

- https://learn.microsoft.com/en-us/linkedin/marketing/versioning
- https://learn.microsoft.com/en-us/linkedin/marketing/integrations/recent-changes
- https://learn.microsoft.com/en-us/linkedin/shared/api-guide/concepts/rate-limits
- https://learn.microsoft.com/en-us/linkedin/shared/api-guide/concepts/error-handling

### Analytics

- https://learn.microsoft.com/en-us/linkedin/marketing/community-management/members/post-statistics
- https://learn.microsoft.com/en-us/linkedin/marketing/community-management/community-management-overview

### n8n

- https://docs.n8n.io/integrations/builtin/app-nodes/n8n-nodes-base.telegram/
- https://docs.n8n.io/hosting/securing/security-audit/
- https://docs.n8n.io/hosting/scaling/external-storage/

## 4. Candidate evidence

- current supplied CV;
- https://github.com/iurii-izman/
- https://github.com/iurii-izman/professional-certifications
- https://github.com/iurii-izman/ai-lead-intake-bitrix24
- https://github.com/iurii-izman/bitrix24-communication-summary-agent

For every migration record access date, selected docs version, endpoint, scope, fixture and live-smoke result.
