# Codex Prompt — Stage 2 n8n Content and Approval Workflows

Precondition: reliable text core accepted.

Implement Telegram intake, evidence builder, structured generator, deterministic and LLM QA orchestration, preview, approve/reject/regenerate/edit/schedule callbacks, due-job scheduler, outbox and OAuth watchdog.

Rules:

- n8n never calls LinkedIn directly;
- n8n never stores LinkedIn token;
- callbacks idempotent;
- chat/user allowlist;
- prompts under `prompts/`;
- exports contain no credentials;
- publisher-api is source of truth;
- add reproducible workflow tests.
