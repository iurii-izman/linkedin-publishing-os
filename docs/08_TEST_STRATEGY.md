# Test Strategy

## 1. Priority

The highest risks are publishing the wrong version, publishing twice, leaking credentials and misrepresenting evidence. Testing follows those risks.

## 2. Layers

### Unit

Fingerprints, transitions, evidence classes, deterministic QA, error/retry classification, OAuth status, redaction and timezone conversion.

### PostgreSQL integration

Unique fingerprints, row locks, concurrent acquisition, transaction rollback, outbox atomicity and migrations.

### LinkedIn adapter contract

Local mock server verifies method, path, headers, version, body, timeout, response parsing, `x-restli-id`, error mapping and redaction.

### API

Authentication, validation, idempotency, state conflicts, no token exposure and stable error format.

### n8n

Mock publisher-api, replayed triggers, duplicate callbacks, outage and notification behavior.

### Live smoke

Manual only: OAuth, text, image and later PDF. Never part of CI.

## 3. Critical matrix

| Scenario | Expected |
|---|---|
| Approve v1, create v2 | v1 approval invalid for active use |
| Same callback twice | one approval |
| Two scheduler runs | one lock and one publish |
| Expired token | `AUTH_REQUIRED`, job preserved |
| 429 | delayed retry, no duplicate |
| 400 | no retry |
| Timeout before final request | safe failure/retry |
| Timeout after final request start | `PUBLISH_UNCERTAIN` |
| 201 + ID | `PUBLISHED` |
| 201 without ID | anomaly/uncertain |
| Asset bytes changed | approval invalid |
| Portfolio rendered as production | QA fail |
| Secret pattern | QA fail |
| Unsupported API version | publishing blocked |
| Unknown Telegram user | rejected |

## 4. Properties

- identical canonical inputs produce identical fingerprints;
- material text or asset change changes approval fingerprint;
- invalid transitions always fail;
- published state always has post URN;
- uncertain jobs never appear in due query;
- unverified claims never survive deterministic QA.

## 5. OAuth tests

Entropy, expiry, replay, callback error, missing code, token expiry parsing, encryption, response serialization and 401 transition.

## 6. Media tests

Wrong MIME, oversized file, checksum, upload expiry, upload failure, processing failure, available state and temporary URL redaction.

## 7. Security tests

No token in logs/exceptions, SQL remains parameterized, unknown Telegram rejected, prompt injection cannot alter policy, malicious markdown sanitized and internal API requires auth.

## 8. Migration tests

Create prior schema, upgrade, verify, downgrade where supported, upgrade again and run repositories.

## 9. CI gates

```text
lint
format-check
type-check
unit
postgres-integration
contract
security-scan
docker-build
docs-links
```

No live LinkedIn secret in CI.
