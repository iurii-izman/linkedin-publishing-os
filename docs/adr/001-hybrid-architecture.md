# ADR-001: Hybrid FastAPI + n8n architecture

**Status:** Accepted

Use FastAPI/PostgreSQL for domain state and LinkedIn integration. Use n8n for triggers, LLM orchestration, Telegram and scheduling calls.

Critical publishing logic needs transactions, typed tests, isolated versioning and secret control. Stage 0 may use temporary raw n8n HTTP nodes; production workflows call publisher-api only.
