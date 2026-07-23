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

## 2.1 Fact classification

- **Verified current fact:** supported directly by an official source below, accessed
  23 July 2026.
- **Real-portal observation:** must be recorded by the owner in
  `docs/feasibility_report.md`.
- **Implementation decision:** repository behavior chosen in the master spec/ADRs.
- **Deferred capability:** not implemented or requested during Stage 0.

Documentation verification never upgrades a real-portal observation to confirmed.

## 3. Official source registry

**Access date for every URL in this registry: 23 July 2026.**

### Access and OAuth

- https://learn.microsoft.com/en-us/linkedin/shared/authentication/getting-access
- https://learn.microsoft.com/en-us/linkedin/shared/authentication/authentication
- https://learn.microsoft.com/en-us/linkedin/shared/authentication/authorization-code-flow
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
- https://docs.n8n.io/integrations/builtin/trigger-nodes/n8n-nodes-base.telegramtrigger/
- https://docs.n8n.io/integrations/builtin/app-nodes/n8n-nodes-base.linkedin/
- https://docs.n8n.io/hosting/securing/security-audit/
- https://docs.n8n.io/hosting/scaling/external-storage/
- https://docs.n8n.io/hosting/configuration/environment-variables/executions/
- https://docs.n8n.io/hosting/configuration/configuration-examples/encryption-key/
- https://docs.n8n.io/source-control-environments/create-environments/

## 4. Candidate evidence

- CV reference named in `data/candidate_evidence_seed.yaml` (not bundled; owner
  verification required);
- https://github.com/iurii-izman/
- https://github.com/iurii-izman/professional-certifications
- https://github.com/iurii-izman/ai-lead-intake-bitrix24
- https://github.com/iurii-izman/bitrix24-communication-summary-agent

For every migration record access date, selected docs version, endpoint, scope, fixture and live-smoke result.

## 5. Verified results versus remaining observations

| Area | Verified from official documentation | Still requires Stage 0 |
|---|---|---|
| Products/scopes | OIDC profile access and Share `w_member_social` are open consumer permissions | Actual app products/scopes |
| OAuth | exact redirect, code flow, state comparison, `expires_in`; programmatic refresh is limited | returned fields and expiry |
| Identity | UserInfo returns pairwise `sub` | accepted person URN |
| Posts | `/rest/posts`, headers, 201, `x-restli-id`; Posts replaces ugcPosts | personal member behavior |
| Version | July 2026 header is `202607` | actual endpoint acceptance |
| Images | initialize/upload/status/final post flow | actual member image access |
| Analytics | `r_member_postAnalytics` belongs to restricted Community Management access | deferred; not an MVP gate |
| n8n | Telegram callback answer, audit and pruning/storage controls exist | Stage 2 workflow behavior |
