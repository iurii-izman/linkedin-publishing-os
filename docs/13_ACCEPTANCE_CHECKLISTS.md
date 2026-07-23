# Acceptance Checklists

## Stage 0

- [x] safe harness, mock tests and manual guide prepared;
- [x] no secret committed (pattern scan and ignored local secret paths);
- [ ] products/scopes recorded;
- [x] OAuth state entropy, expiry and replay validated with mocks;
- [ ] token lifetime observed;
- [ ] author URN validated;
- [ ] `/rest/posts` tested;
- [ ] post URN captured;
- [ ] image tested;
- [ ] 401 behavior recorded;
- [ ] GO decision written.

## Text MVP

- [ ] immutable draft;
- [ ] approval binds exact hash;
- [ ] edit invalidates approval;
- [ ] UTC schedule;
- [ ] concurrent execution publishes once;
- [ ] 201 stores URN;
- [ ] 400 no retry;
- [ ] 401 preserves job;
- [ ] 429 backoff;
- [ ] final timeout uncertain;
- [ ] uncertain never auto-executes;
- [ ] reliable outbox;
- [ ] no token in logs.

## Content engine

- [ ] every factual claim has evidence ID;
- [ ] unverified claim blocked;
- [ ] private source not linked;
- [ ] portfolio not called production;
- [ ] commercial proof accurate;
- [ ] deterministic QA stored;
- [ ] LLM cannot override hard fail;
- [ ] Telegram preview exact;
- [ ] callback replay safe.

## Image/document

- [ ] MIME/size/structure validated;
- [ ] checksum computed;
- [ ] approval binds checksum;
- [ ] upload URL not logged;
- [ ] media URN stored;
- [ ] alt text reviewed;
- [ ] document only publishes when available;
- [ ] processing failure classified.

## Security

- [ ] token encrypted;
- [ ] DB dump has no plaintext token;
- [ ] internal API auth;
- [ ] Telegram allowlist;
- [ ] state replay rejected;
- [ ] secret scan clean;
- [ ] n8n audit reviewed;
- [ ] backup restore tested;
- [ ] no browser automation dependencies.

## Production readiness

- [ ] API version current;
- [ ] migration revision known;
- [ ] backup current;
- [ ] rollback documented;
- [ ] scheduler enabled after smoke;
- [ ] uncertain/auth alerts;
- [ ] first queue reviewed;
- [ ] limitations documented.
