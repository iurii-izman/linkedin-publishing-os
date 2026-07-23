# Implementation Plan and Stage Gates

## Principle

Build vertical slices. Do not build content intelligence before proving LinkedIn access. Do not build media before reliable text publishing.

## Stage 0 — Feasibility

Output:

- sanitized report;
- OAuth evidence;
- author URN method;
- selected endpoint/version;
- text and image smoke;
- GO/GO_WITH_LIMITATIONS/NO_GO.

`NO_GO` changes the product to draft-and-reminder mode. It never triggers browser automation.

Stage 0 implementation is an isolated spike, not the Stage 1 foundation. Text
publication is the required GO signal. If text succeeds but image access is
unavailable, the owner may record `GO_WITH_LIMITATIONS`; media remains blocked until
separately validated.

## Stage 1 — Foundation and reliable text

1. Repo, settings, health, PostgreSQL, Alembic and CI.
2. OAuth sessions, encrypted token, status and author URN.
3. Minimal evidence/draft model and immutable versions.
4. Approval fingerprint, jobs, scheduler command, text adapter, post URN, audit/outbox.
5. Concurrency, uncertain state, notifications and deployment.

Gate: a manually created approved draft is safely scheduled and published as text.

## Stage 2 — Content pipeline

1. Telegram intake and candidate evidence seed.
2. Structured generator and deterministic QA.
3. LLM QA and Telegram preview.
4. Edit/regenerate/schedule and weekly queue.

Gate: Telegram idea reaches scheduled text post without editing DB/workflows.

## Stage 3 — Media

1. Asset storage, validation and checksum.
2. Image upload/post and alt text.
3. PDF/document upload, status polling and post.

Gate: correct approved asset publishes; changed bytes invalidate approval.

## Stage 4 — Intelligence

GitHub/RSS policies, similarity, pillar balance, weekly review and manual outcome metrics.

## Stage 5 — Optional analytics

Only after actual `r_member_postAnalytics` approval. Manual fallback remains.

## Definition of Done

Acceptance met, tests pass, migration tested, docs updated, no secrets, observability present, error path tested, task marked and no unresolved critical TODO.

## Anti-patterns

Do not scaffold all future components, build frontend first, scatter prompts through nodes, use Telegram/Notion as state, call LinkedIn from multiple workflows, retry in both n8n and API, add Redis early or let LLM approve its own text.
