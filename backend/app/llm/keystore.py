"""API key storage.

The key lives in server memory keyed by an opaque session token. The browser only ever sees the
token. If the user ticks "remember key on this server", the key is also written to SQLite encrypted
with Fernet, using a secret derived from ``KEY_ENCRYPTION_SECRET``.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import time
from dataclasses import dataclass

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.errors import InvalidKeyError
from app.models.orm import ApiKeyRecord

TOKEN_BYTES = 32
SESSION_TTL_SECONDS = 12 * 60 * 60


def fernet_for(secret: str) -> Fernet:
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def fingerprint(api_key: str) -> str:
    return api_key[-4:] if len(api_key) >= 4 else "****"


@dataclass(slots=True)
class _Entry:
    api_key: str
    created_at: float
    fingerprint: str


class KeyStore:
    """In-memory session keys plus optional encrypted persistence."""

    def __init__(self, secret: str, *, ttl_seconds: int = SESSION_TTL_SECONDS) -> None:
        self._fernet = fernet_for(secret)
        self._entries: dict[str, _Entry] = {}
        self._ttl = ttl_seconds

    def _purge(self) -> None:
        cutoff = time.monotonic() - self._ttl
        for token, entry in list(self._entries.items()):
            if entry.created_at < cutoff:
                del self._entries[token]

    def put(self, api_key: str) -> str:
        self._purge()
        token = secrets.token_urlsafe(TOKEN_BYTES)
        self._entries[token] = _Entry(
            api_key=api_key, created_at=time.monotonic(), fingerprint=fingerprint(api_key)
        )
        return token

    def get(self, token: str | None) -> str | None:
        if not token:
            return None
        self._purge()
        entry = self._entries.get(token)
        return entry.api_key if entry else None

    def require(self, token: str | None) -> str:
        key = self.get(token)
        if key is None:
            raise InvalidKeyError("Your session expired. Paste your API key again.")
        return key

    def fingerprint_of(self, token: str | None) -> str | None:
        entry = self._entries.get(token) if token else None
        return entry.fingerprint if entry else None

    def forget(self, token: str) -> None:
        self._entries.pop(token, None)

    # ------------------------------------------------------------ persistence
    async def remember(self, session: AsyncSession, token: str, api_key: str) -> None:
        record = ApiKeyRecord(
            session_token_hash=token_hash(token),
            ciphertext=self._fernet.encrypt(api_key.encode("utf-8")).decode("ascii"),
            fingerprint=fingerprint(api_key),
        )
        await session.merge(record)
        await session.commit()

    async def restore(self, session: AsyncSession, token: str) -> str | None:
        """Load a remembered key back into memory (used after a server restart)."""
        cached = self.get(token)
        if cached:
            return cached
        stmt = select(ApiKeyRecord).where(ApiKeyRecord.session_token_hash == token_hash(token))
        record = (await session.execute(stmt)).scalar_one_or_none()
        if record is None:
            return None
        try:
            api_key = self._fernet.decrypt(record.ciphertext.encode("ascii")).decode("utf-8")
        except InvalidToken:
            return None
        self._entries[token] = _Entry(
            api_key=api_key, created_at=time.monotonic(), fingerprint=record.fingerprint
        )
        return api_key

    async def forget_everywhere(self, session: AsyncSession, token: str) -> None:
        self.forget(token)
        await session.execute(
            delete(ApiKeyRecord).where(ApiKeyRecord.session_token_hash == token_hash(token))
        )
        await session.commit()
