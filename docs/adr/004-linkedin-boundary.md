# ADR-004: publisher-api is the sole LinkedIn boundary

**Status:** Accepted after Stage 0 validation

All production OAuth, media and post calls live in the FastAPI adapter. n8n does not hold production LinkedIn tokens or duplicate payload/retry logic.
