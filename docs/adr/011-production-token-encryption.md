# ADR-011: Versioned authenticated token encryption

**Status:** Accepted for Stage 1 design

Production OAuth tokens use a maintained authenticated-encryption implementation.
Ciphertext is stored as `v1:<key-id>:<base64-ciphertext>` and includes integration ID
and owner key as authenticated associated data. Encryption keys remain outside
PostgreSQL, logs, n8n and workflow exports. Rotation decrypts with the old key and
rewrites under the active key in a bounded audited operation.

The Stage 0 Fernet ciphertext from ADR-009 is isolated spike state and must not be
copied into the production database. The owner-only Stage 1 import command may read
and decrypt that record in memory, validate it, and immediately re-encrypt the token
as a Stage 1 AEAD record with connection identity as associated data. The original
ignored Stage 0 store remains unchanged.
