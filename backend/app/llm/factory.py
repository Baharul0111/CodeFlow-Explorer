"""Build a :class:`ClaudeClient` for a request (real or mock, decided by configuration)."""

from __future__ import annotations

from app.config import Settings
from app.llm.client import AnthropicClaudeClient, ClaudeClient
from app.llm.errors import InvalidKeyError
from app.llm.mock import MockClaudeClient


def make_client(settings: Settings, api_key: str | None) -> ClaudeClient:
    if settings.is_mock:
        return MockClaudeClient()
    if not api_key:
        raise InvalidKeyError("Connect your Anthropic API key first.")
    return AnthropicClaudeClient(api_key)
