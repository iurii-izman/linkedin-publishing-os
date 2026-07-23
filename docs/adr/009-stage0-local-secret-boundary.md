# ADR-009: Stage 0 uses an encrypted local connection store

**Status:** Accepted for Stage 0 only

The feasibility harness runs as one trusted process. OAuth state is random, one-time,
hashed in memory and expires after 15 minutes. The callback encrypts the complete
connection record with Fernet and writes it to `.stage0/`, which is ignored by Git.
The key comes from `TOKEN_ENCRYPTION_KEY` and is never stored beside ciphertext.

This deliberately avoids PostgreSQL before feasibility is known. Restarting the
callback process invalidates outstanding OAuth states. That is acceptable for the
owner-operated spike and is not acceptable for Stage 1, where OAuth sessions and
versioned AEAD ciphertext must be persisted transactionally.

