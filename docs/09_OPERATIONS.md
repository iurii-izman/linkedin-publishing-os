# Deployment and Operations

## 1. Initial topology

A small trusted VPS or host:

```text
Caddy/Traefik/Nginx
publisher-api
n8n
PostgreSQL
asset volume
backup job
```

Pin versions. Do not use floating `latest` in production.

`docker-compose.example.yml` demonstrates separate least-privilege `publisher` and
`n8n` databases/users. Its placeholder secrets must be replaced before use. The
current `publisher-api` image exposes only the Stage 0 harness; this Compose file is
not evidence of a production deployment.

n8n 2.30.5 starts its bundled JavaScript runner but the official image reports that
an internal Python runner is unavailable. Stage 0 uses neither. Before any future
Code-node workflow is admitted, Stage 2 must choose and harden the documented
external task-runner topology; this example does not claim production runner
readiness.

## 2. Environments

At least local development and production. Live tests use clearly labeled controlled posts; configuration and secrets are separate.

## 3. Health

`/health` checks process only. `/ready` checks DB, migration revision, encryption service, storage and settings. LinkedIn availability is a separate status and must not make the app unready.

## 4. Monitoring

Track jobs by state, oldest due job, publish outcomes, auth days remaining, outbox backlog, media duration, API latency, DB errors and n8n failures.

Alerts:

- any `PUBLISH_UNCERTAIN`;
- `AUTH_REQUIRED` or expiring auth;
- due job older than 30 minutes;
- outbox older than 15 minutes;
- repeated 429;
- unsupported API version;
- backup failure;
- disk threshold.

## 5. Backup

Database: daily encrypted backup, 7 daily, 4 weekly and 6 monthly initially, off-host copy and monthly restore test.

Assets: retain according to policy. n8n: secure instance backup plus workflow exports; credentials never go to Git.

Initial RPO 24 hours, RTO 4 hours.

## 6. OAuth operations

Daily watchdog. States: `CONNECTED`, `EXPIRING`, `AUTH_REQUIRED`, `REVOKED`, `MISCONFIGURED`.

Reauthorization pauses due execution, completes protected OAuth, verifies author URN/capability and resumes jobs.

## 7. API version maintenance

Monthly:

1. check official version page and recent changes;
2. select supported version;
3. update test config;
4. run contract suite;
5. run controlled smoke when payload behavior changed;
6. update production config and record result.

## 8. Rate limits

Use low frequency, avoid redundant polling, cache capability/status, honor `Retry-After` and use jittered backoff. Review actual limits in Developer Portal.

## 9. Pruning

Prune successful n8n executions, keep failures longer, avoid binaries in executions, delete expired OAuth sessions and temporary upload metadata, and preserve published audit.

## 10. Runbook — uncertain publish

Stop automation for the job, check LinkedIn manually, resolve as published with URN or not published, and preserve the original attempt. Only a resolved not-published state can create a controlled new attempt.

## 11. Runbook — rollback

Pause scheduler, back up DB, record current images and migration revision, validate downgrade support and preserve queued jobs.

## 12. Stage 1 immediate-text operations

The implemented migration, readiness behavior, safe connection import, stale
`PUBLISHING` reconciliation, backup/restore procedure and controlled live checkpoint
are documented in [`STAGE1_VERTICAL_MVP.md`](STAGE1_VERTICAL_MVP.md). Stage 1 does
not start migrations automatically and has no retry command for terminal
publications.
