# Product Requirements Document

## 1. Problem

Regular LinkedIn publishing is useful for professional positioning, but the work is fragmented:

- ideas are lost across Telegram, GitHub, RSS and notes;
- generic AI-generated posts damage credibility;
- commercial experience and portfolio work can be accidentally conflated;
- every post requires repetitive drafting, translation, formatting and scheduling;
- OAuth and platform APIs can fail;
- blind automation creates account and reputational risk.

The owner needs regularity without delegating judgment or fabricating expertise.

## 2. Job to be done

> When I have a useful professional observation, project change or source, help me turn it into an evidence-backed LinkedIn post, let me approve the exact final version, publish it safely on schedule and preserve a reliable record.

## 3. User journeys

### Telegram idea to text post

1. Owner sends a note to the Telegram bot.
2. n8n normalizes and stores it.
3. The system selects evidence.
4. LLM creates a structured draft.
5. QA passes.
6. Telegram shows preview and actions.
7. Owner approves and schedules.
8. publisher-api publishes.
9. Telegram returns status and post identity.

### GitHub release to applied lesson

A selected public release is filtered for professional value. The system produces a practical lesson, not a changelog, and preserves portfolio qualifiers.

### OAuth expires

The integration becomes `AUTH_REQUIRED`; scheduled jobs remain queued; reauthorization restores eligibility without recreating work.

### Ambiguous publish result

A timeout after the final request becomes `PUBLISH_UNCERTAIN`. No automatic retry occurs. The owner verifies LinkedIn and resolves the state.

### Draft edited after approval

Any text, asset, language or visibility change invalidates the previous approval.

## 4. Functional requirements

- **FR-001:** accept text, URL and supported source events.
- **FR-002:** deduplicate exact sources by canonical URL and content hash.
- **FR-003:** require an evidence pack before a publishable draft.
- **FR-004:** use structured draft output.
- **FR-005:** map substantive factual statements to claim IDs.
- **FR-006:** run deterministic and model-based QA.
- **FR-007:** keep draft versions immutable.
- **FR-008:** bind approval to exact text and asset fingerprints.
- **FR-009:** accept local scheduling time and store UTC.
- **FR-010:** publish only through official LinkedIn APIs.
- **FR-011:** preserve jobs through OAuth failures.
- **FR-012:** block concurrent duplicate execution.
- **FR-013:** distinguish failed from uncertain publication.
- **FR-014:** support text and one image in MVP.
- **FR-015:** audit every material state transition.
- **FR-016:** notify through Telegram.
- **FR-017:** expose and enforce API capability flags.
- **FR-018:** store manual metric snapshots.
- **FR-019:** gate API analytics behind actual approved scope.

## 5. Non-functional requirements

### Reliability

- transactional state transitions;
- safe concurrent scheduler;
- no destructive cleanup before final state;
- test-restorable backups.

### Security

- encrypted tokens;
- no secrets in workflow exports;
- HTTPS callbacks;
- Telegram allowlist;
- authenticated internal API;
- redacted logs.

### Maintainability

- LinkedIn adapter isolated;
- API version configurable;
- n8n uses stable commands;
- schemas and migrations versioned.

### Performance

Low volume. Correctness is primary.

- ordinary internal API under 500 ms excluding external calls;
- due-job acquisition under 2 seconds;
- Telegram acknowledgement under 3 seconds;
- content generation may take up to 90 seconds with progress feedback.

## 6. Content requirements

Posts should:

- start with a concrete work problem or observation;
- show one practical mechanism;
- include one micro-proof;
- avoid generic AI evangelism;
- separate commercial experience from prototypes;
- use natural Russian or clear professional English B2;
- avoid inflated claims;
- end with a useful conclusion.

Default balance:

- CRM/Bitrix24 — 30%;
- integrations/data quality — 30%;
- systems analysis/acceptance — 20%;
- applied AI automation — 20%.

## 7. Release scope

### MVP

Feasibility, OAuth, text, one image, source intake, evidence, structured generation, QA, Telegram approval, scheduling, audit, manual metrics, deployment and backup.

### Next

PDF/document posts, similarity, GitHub release automation and weekly review.

### Later

Multi-image, lightweight web dashboard and separate adapters for other platforms.
