"""Content-hash cache for LLM answers.

Key = sha256(task | model | prompt version | payload). Identical code in another project, or a
re-upload of the same project, therefore costs nothing.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.orm import LlmCache


def cache_key(*, task: str, model: str, prompt_version: str, payload: dict[str, Any]) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    digest = hashlib.sha256(f"{task}\0{model}\0{prompt_version}\0{blob}".encode())
    return digest.hexdigest()


class ResponseCache:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, key: str) -> dict[str, Any] | None:
        row = await self._session.get(LlmCache, key)
        return dict(row.response) if row is not None else None

    async def put(self, key: str, *, task: str, model: str, response: dict[str, Any]) -> None:
        await self._session.merge(LlmCache(key=key, task=task, model_id=model, response=response))
        await self._session.commit()
