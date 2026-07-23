from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from pydantic import BaseModel, ConfigDict, Field, SecretStr


class StoredConnection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    access_token: SecretStr
    expires_at: datetime
    granted_scopes: list[str]
    member_subject: str = Field(min_length=1, max_length=200)
    author_urn: str
    api_version: str


class EncryptedConnectionStore:
    def __init__(self, path: Path, key: SecretStr) -> None:
        self._path = path
        self._fernet = Fernet(key.get_secret_value().encode("ascii"))

    def save(self, connection: StoredConnection) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        serialized = connection.model_dump(mode="json")
        serialized["access_token"] = connection.access_token.get_secret_value()
        plaintext = json.dumps(serialized, separators=(",", ":")).encode("utf-8")
        ciphertext = self._fernet.encrypt(plaintext)
        file_descriptor, temporary_name = tempfile.mkstemp(dir=self._path.parent)
        try:
            with os.fdopen(file_descriptor, "wb") as stream:
                stream.write(ciphertext)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary_name, 0o600)
            os.replace(temporary_name, self._path)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)

    def load(self) -> StoredConnection:
        try:
            plaintext = self._fernet.decrypt(self._path.read_bytes())
        except (FileNotFoundError, InvalidToken) as exc:
            raise ValueError("No readable encrypted Stage 0 connection is available") from exc
        return StoredConnection.model_validate(json.loads(plaintext))
