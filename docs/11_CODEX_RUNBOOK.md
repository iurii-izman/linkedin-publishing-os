# Codex Development Runbook

## 1. Method

Use one approved task at a time. Inspect relevant files, propose a short plan, implement, run checks and update docs.

## 2. First session

Use `prompts/00_REPOSITORY_KICKOFF.md`. Do not ask Codex to build the whole product in one prompt.

## 3. Task template

```text
Implement task LPOS-XYZ from TASKS.md.

Read:
- AGENTS.md
- MASTER_SPEC.md
- relevant docs and ADRs
- specs/openapi.yaml
- specs/schema.sql

Constraints:
- keep scope limited;
- do not weaken approval, token handling or duplicate protection;
- use synthetic fixtures;
- no live LinkedIn calls in tests;
- update docs/contracts when behavior changes.

Before coding:
1. inspect the repository;
2. restate task and affected boundaries;
3. identify migration/API changes;
4. list acceptance tests.

Then implement, run checks and report exact results.
```

## 4. Review template

```text
Review the diff against AGENTS.md and MASTER_SPEC.md.
Focus on security, invariants, ambiguous publishing, token leakage,
retries, contract drift, missing tests and docs drift.
Report findings by severity with exact files and lines.
```

## 5. Stage discipline

Do not implement Stage 1 before Stage 0 GO. Mocks may be built but not described as verified LinkedIn integration.

## 6. Repository memory

Maintain feasibility report, ADRs, tasks, release notes, migrations, fixtures and known limitations. Decisions belong in repo, not only chat.

## 7. Prompt changes

Prompts are product code: version them, use schemas, add fixtures and regression cases, and record rationale.

## 8. n8n changes

Workflow JSON is code. Remove credentials, use readable names, shared sub-workflows, manifest and replay/error tests. No direct production LinkedIn call.

## 9. Live test protocol

Codex prepares steps. Owner performs real OAuth/posting with synthetic content, one post, sanitized evidence and no credentials pasted into chat.

## 10. Completion format

```text
Status: COMPLETE | PARTIAL | BLOCKED
Implemented:
Files:
Checks:
Acceptance:
Known limitations:
Docs updated:
Next task:
```
