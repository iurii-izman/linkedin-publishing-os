# AGENTS.md — Codex Operating Contract

This repository implements a single-user LinkedIn publishing system. Read this file before every substantial task.

## Mandatory read order

1. `AGENTS.md`
2. `MASTER_SPEC.md`
3. the relevant detailed document under `docs/`
4. applicable ADRs
5. `specs/openapi.yaml` and `specs/schema.sql`
6. the active task in `TASKS.md`

## Non-negotiable product boundaries

- Use official LinkedIn OAuth and APIs only.
- Never add browser automation, scraping, Playwright, Selenium, extension-driven actions, or hidden UI automation.
- Never automate connection requests, direct messages, profile visits, reactions, comments, or engagement farming.
- Never publish without a valid approval bound to the exact text hash and asset checksum.
- Never silently retry a final post creation call after a network timeout or ambiguous response.
- Never expose LinkedIn access tokens to n8n, Telegram, logs, traces, exception messages, or API responses.
- Never store client PII, real CRM records, confidential employer data, or private repository content in generated posts.
- Portfolio and demo projects must remain explicitly separated from commercial experience.
- Do not claim production deployment, metrics, customers, team size, ownership, or outcomes unless present in the evidence store.

## Architecture rules

- `publisher-api` is the sole LinkedIn API boundary and source of domain state.
- PostgreSQL is the authoritative state store.
- n8n orchestrates; it must not duplicate domain state or LinkedIn publishing logic.
- Telegram is an approval interface, not a source of truth.
- LinkedIn API version must be configurable.
- OAuth tokens must be encrypted at rest.
- State transitions must be explicit and transactionally enforced.
- Final post creation must be protected by a database lock and publication fingerprint.
- Any change to contracts requires updating docs, tests, and schemas in the same change.

## Development rules

- Resolve the smallest complete vertical slice.
- Prefer typed code and explicit schemas over dynamic dictionaries.
- Use Python 3.12+, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, PostgreSQL, httpx and pytest unless an ADR changes this.
- Use dependency injection for LinkedIn, clock, ID generation, token encryption and LLM boundaries.
- All external calls require timeouts.
- Retry only when the operation is demonstrably safe.
- Keep fixtures synthetic and public-safe.
- No production network calls in automated tests.
- Do not mark a task complete until tests, lint, type checks and docs are updated.

## Quality gates

```bash
ruff check .
ruff format --check .
mypy .
pytest -q
```

When API contracts or migrations change:

```bash
alembic upgrade head
alembic downgrade -1
alembic upgrade head
```

When Docker or deployment changes:

```bash
docker compose config
docker compose up -d --build
# run smoke checks
docker compose down
```

## Commit discipline

Use focused commits:

- `feat: ...`
- `fix: ...`
- `test: ...`
- `docs: ...`
- `refactor: ...`
- `chore: ...`

Do not combine unrelated refactors with feature work. Do not rewrite large files without need.

## Task completion report

Every Codex completion must report:

1. What changed.
2. Files changed.
3. Tests and checks run with exact result.
4. Known limitations.
5. Documentation updated.
6. Next recommended task.
7. Whether any assumption still needs real LinkedIn validation.

## Stop conditions

Stop and ask for a decision when:

- LinkedIn does not grant a required product or scope.
- `/rest/posts` behavior differs from the source-of-truth documentation.
- a requested feature would require prohibited browser automation;
- a state transition cannot be implemented without weakening approval or duplicate protection;
- a change requires storing new sensitive data;
- the task would make portfolio claims appear commercial.
