# Security, Privacy and Threat Model

## 1. Critical assets

- LinkedIn client secret and access token;
- token-encryption key;
- internal API credential;
- Telegram bot token;
- database backup key;
- unpublished drafts and private sources.

## 2. Trust boundaries

```text
owner device ↔ Telegram
Telegram ↔ n8n
n8n ↔ publisher-api
publisher-api ↔ PostgreSQL
publisher-api ↔ LinkedIn
publisher-api ↔ asset storage
internet ↔ reverse proxy
```

Every crossing requires authentication, validation and bounded payload size.

## 3. Threats and controls

### Token theft

Backend-only exchange, encrypted token column, key outside DB, no token in n8n, redacted logs, least-privilege scopes and reauthorization after suspected leak.

### OAuth CSRF

Random one-time `state`, expiry, exact redirect URI and no callback without valid state.

### Telegram impersonation

Chat/user allowlist, opaque callback IDs, replay protection and audited approver identity.

### Prompt injection

Source content is data, never instructions. Generation nodes have no tools. Claims are allowlisted deterministically.

### Confidential leakage

Source visibility, public-allowance flag, secret/PII scanning, preview and mandatory approval.

### Duplicate publication

Unique fingerprint, DB lock, attempt phase and terminal uncertain state.

### Supply-chain risk

Pinned dependencies, lock file, secret scan, dependency scan, container scan and no unreviewed n8n community nodes.

### SSRF

URL allowlists, block private network for generic fetch, validate LinkedIn upload hosts and avoid generic proxy endpoints.

For current Stage 0 image upload, accept only HTTPS URLs with host
`www.linkedin.com` and path prefix `/dms-uploads/`. Do not follow a returned upload
URL to another host.

### Malicious files

MIME/extension/size validation, PDF structural validation, no macro-enabled documents and optional antivirus scan.

### SQL injection

Bound parameters, no raw expression SQL from n8n and separate DB roles.

## 4. Secret storage

publisher-api environment/secret manager stores client secret, encryption key and internal token. DB stores only encrypted access token and safe metadata.

n8n credentials store Telegram, API service, LLM and GitHub credentials. Production LinkedIn access token does not remain in n8n after Stage 0.

## 5. Encryption

Use maintained authenticated encryption. Ciphertext must be versioned and rotation-ready, for example:

```text
v1:<key-id>:<base64-ciphertext>
```

Plaintext exists only immediately before the API call.

Production ciphertext authenticates integration identity as associated data and
includes a key ID for rotation (ADR-011). The Stage 0 Fernet file is a disposable
spike boundary and is never imported into the production database (ADR-009).

## 6. Logging

Allowed: timestamp, event, correlation ID, entity ID, attempt ID, endpoint class, safe error code and latency.

Redact: headers, tokens, auth code, upload URL query, private body and final post text from low-level network logs.

## 7. Deployment hardening

- HTTPS only;
- secure cookies and trusted proxy settings;
- n8n MFA;
- no public DB;
- fixed `N8N_ENCRYPTION_KEY`;
- restrict webhooks;
- non-root containers where supported;
- encrypted backups;
- firewall only required ports.

## 8. n8n controls

Run `n8n audit`, block unnecessary risky nodes, avoid Execute Command, prune executions, avoid retaining binaries and export workflows without credentials.

## 9. Incident runbooks

### LinkedIn token leak

Disable publishing, revoke app authorization, rotate exposed secrets/keys, reauthorize, inspect audit and record incident.

### Telegram token leak

Revoke bot token, replace credential, invalidate pending callbacks and review approvals in the exposure window.

### Unexpected post

Stop scheduler, preserve records, delete manually if required, compare approval fingerprint, add regression test and resume only after review.

## 10. Security acceptance

Production is blocked unless token redaction, DB encryption, internal auth, Telegram allowlist, OAuth replay rejection, secret scan, n8n audit, backup restore and no-browser-automation checks pass.
