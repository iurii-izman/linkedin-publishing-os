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

- [x] immutable draft revision;
- [x] approval binds exact hash;
- [x] new revision invalidates old approval for active use;
- [ ] UTC schedule;
- [x] concurrent immediate execution publishes once;
- [x] 201 stores URN;
- [x] unambiguous 400 no retry;
- [ ] 401 preserves job;
- [ ] 429 backoff;
- [x] final timeout uncertain;
- [x] uncertain never auto-executes;
- [ ] reliable outbox;
- [x] no token in logs.

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

- [x] Stage 1 token encrypted;
- [x] PostgreSQL stores no plaintext token;
- [x] owner API auth;
- [ ] Telegram allowlist;
- [ ] state replay rejected;
- [x] tracked and candidate secret scans clean;
- [ ] n8n audit reviewed;
- [ ] backup restore tested;
- [x] no browser automation dependencies.

## Production readiness

- [ ] API version current;
- [ ] migration revision known;
- [ ] backup current;
- [ ] rollback documented;
- [ ] scheduler enabled after smoke;
- [ ] uncertain/auth alerts;
- [ ] first queue reviewed;
- [ ] limitations documented.
