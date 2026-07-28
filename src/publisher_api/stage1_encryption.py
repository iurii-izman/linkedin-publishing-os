from __future__ import annotations

import base64
import os
from dataclasses import dataclass

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic import SecretStr


@dataclass(frozen=True, repr=False)
class TokenCipher:
    key: SecretStr
    key_id: str

    def _key_bytes(self) -> bytes:
        try:
            decoded = base64.urlsafe_b64decode(self.key.get_secret_value().encode("ascii"))
        except (ValueError, UnicodeEncodeError) as exc:
            raise ValueError("Stage 1 token encryption key is invalid") from exc
        if len(decoded) != 32:
            raise ValueError("Stage 1 token encryption key must decode to 32 bytes")
        return decoded

    @staticmethod
    def associated_data(connection_id: str, owner_subject: str) -> bytes:
        return f"linkedin-connection:{connection_id}:owner:{owner_subject}".encode()

    def encrypt(self, token: SecretStr, *, connection_id: str, owner_subject: str) -> str:
        nonce = os.urandom(12)
        ciphertext = AESGCM(self._key_bytes()).encrypt(
            nonce,
            token.get_secret_value().encode("utf-8"),
            self.associated_data(connection_id, owner_subject),
        )
        encoded = base64.urlsafe_b64encode(nonce + ciphertext).decode("ascii")
        return f"v1:{self.key_id}:{encoded}"

    def decrypt(self, ciphertext: str, *, connection_id: str, owner_subject: str) -> SecretStr:
        try:
            version, key_id, encoded = ciphertext.split(":", 2)
            if version != "v1" or key_id != self.key_id:
                raise ValueError
            combined = base64.urlsafe_b64decode(encoded.encode("ascii"))
            token = AESGCM(self._key_bytes()).decrypt(
                combined[:12],
                combined[12:],
                self.associated_data(connection_id, owner_subject),
            )
        except Exception as exc:
            raise ValueError("Encrypted Stage 1 token cannot be decrypted") from exc
        return SecretStr(token.decode("utf-8"))
