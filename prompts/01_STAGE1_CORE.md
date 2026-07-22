# Codex Prompt — Stage 1 Reliable Text Publishing Core

Precondition: `docs/feasibility_report.md` states `GO` or `GO_WITH_LIMITATIONS`.

Read AGENTS, Master Spec, architecture, domain model, LinkedIn integration, security, tests, OpenAPI and schema.

Implement:

- FastAPI application;
- PostgreSQL and Alembic;
- encrypted LinkedIn token;
- integration status;
- immutable drafts;
- approval fingerprint;
- publication jobs;
- transactional acquisition;
- LinkedIn text adapter;
- post URN capture;
- uncertain state;
- audit and outbox;
- Docker Compose;
- CI and full tests.

Do not add LLM generation, RSS, GitHub intake, media or web UI. Use a mock LinkedIn server in automated tests. Update `TASKS.md` after each complete vertical slice.
