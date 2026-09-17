"""Shared helpers for turning a session token into an API key and a usable model list."""

from __future__ import annotations

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import AppError
from app.llm.catalog import fallback_models, merge_models, usable_models
from app.llm.client import AnthropicClaudeClient, llm_errors
from app.llm.mock import MockClaudeClient
from app.llm.types import ModelSpec


async def resolve_api_key(request: Request, session: AsyncSession, token: str | None) -> str | None:
    settings = request.app.state.settings
    if settings.is_mock:
        return None
    store = request.app.state.key_store
    api_key: str | None = await store.restore(session, token) if token else None
    if api_key is None and settings.anthropic_api_key:
        api_key = str(settings.anthropic_api_key)
    if api_key is None:
        raise AppError("Connect your Anthropic API key first.", code="no_key", status_code=401)
    return api_key


async def models_for(request: Request, session: AsyncSession, token: str | None) -> list[ModelSpec]:
    settings = request.app.state.settings
    config = settings.load_models_config()
    if settings.is_mock:
        return merge_models(await MockClaudeClient().list_models(), config)
    api_key = await resolve_api_key(request, session, token)
    client = AnthropicClaudeClient(api_key or "")
    try:
        with llm_errors():
            specs = await client.list_models()
    except AppError:
        return fallback_models(config)
    finally:
        await client.aclose()
    return usable_models(merge_models(specs, config))
