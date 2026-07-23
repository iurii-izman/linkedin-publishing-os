# ADR-010: Relational evidence links and single retry owner

**Status:** Accepted

- Evidence-pack/source/claim and draft/claim relationships use join tables, not UUID
  arrays. PostgreSQL foreign keys must prevent dangling evidence.
- n8n owns the five-minute trigger only. `publisher-api` owns due-job acquisition,
  state transitions, LinkedIn calls and every retry classification.
- n8n authenticates with a rotatable service bearer credential. Production should
  replace a shared static value with a secret-manager-backed credential when the
  deployment platform supports it.
- Temporary LinkedIn upload URLs are encrypted only while required and are deleted
  after upload completion or expiry. They never enter audit, outbox or n8n payloads.
- Local/production PostgreSQL uses separate `publisher` and `n8n` databases and
  least-privilege roles. Neither application role is a cluster administrator.
- Manual reconciliation is the only exit from `PUBLISH_UNCERTAIN`; retry policy has
  no second owner in n8n.

