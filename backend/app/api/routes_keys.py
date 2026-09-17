"""Connect-to-Claude endpoints: test a key, list models, forget a key.

The key is accepted once, kept in server memory under an opaque session token, and never returned
to the browser again.
"""

from __future__ import annotations

from fastapi import APIRouter, Header, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.api.deps import ClientKeyDep, LimiterDep, SessionDep, SettingsDep
from app.llm.catalog import (
    fallback_models,
    merge_models,
    pick_deep_model,
    pick_default_model,
    usable_models,
)
from app.llm.client import AnthropicClaudeClient, llm_errors
from app.llm.errors import InvalidKeyError
from app.llm.mock import MockClaudeClient
from app.llm.types import ModelSpec
from app.logging_setup import get_logger

router = APIRouter(prefix="/api/keys", tags=["keys"])
log = get_logger(__name__)


class TestKeyRequest(BaseModel):
    api_key: str = Field(min_length=8, max_length=512)
    remember: bool = False
    verify_spend: bool = True


class TestKeyResponse(BaseModel):
    session_token: str
    key_fingerprint: str
    models: list[ModelSpec]
    suggested_model: str | None
    suggested_deep_model: str | None
    remembered: bool


class ModelsResponse(BaseModel):
    models: list[ModelSpec]
    source: str


def _key_store(request: Request):  # type: ignore[no-untyped-def]
    return request.app.state.key_store


@router.post("/test", response_model=TestKeyResponse)
async def test_key(
    body: TestKeyRequest,
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    limiter: LimiterDep,
    key: ClientKeyDep,
) -> TestKeyResponse:
    limiter.check(f"key:{key}", settings.rate_limit_analysis_per_minute)
    api_key = body.api_key.strip()
    client = MockClaudeClient() if settings.is_mock else AnthropicClaudeClient(api_key)
    try:
        with llm_errors():
            specs = await client.list_models()
            config = settings.load_models_config()
            models = usable_models(merge_models(specs, config))
            if not models:
                raise InvalidKeyError("No usable models are available for this key.")
            if body.verify_spend and not settings.is_mock:
                cheapest = min(models, key=lambda m: m.input_price or 0.0)
                await client.verify_credentials(model=cheapest.id)
    finally:
        await client.aclose()
    store = _key_store(request)
    token = store.put(api_key)
    if body.remember:
        await store.remember(session, token, api_key)
    suggested = pick_default_model(models)
    log.info("key_tested", models=len(models), remembered=body.remember)
    return TestKeyResponse(
        session_token=token,
        key_fingerprint=store.fingerprint_of(token) or "****",
        models=models,
        suggested_model=suggested,
        suggested_deep_model=pick_deep_model(models, suggested) if suggested else None,
        remembered=body.remember,
    )


@router.get("/models", response_model=ModelsResponse)
async def get_models(
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    x_session_token: str | None = Header(default=None),
) -> ModelsResponse:
    config = settings.load_models_config()
    store = _key_store(request)
    api_key = await store.restore(session, x_session_token) if x_session_token else None
    if api_key is None and not settings.is_mock:
        return ModelsResponse(models=fallback_models(config), source="fallback")
    client = MockClaudeClient() if settings.is_mock else AnthropicClaudeClient(api_key or "")
    try:
        with llm_errors():
            specs = await client.list_models()
    finally:
        await client.aclose()
    return ModelsResponse(models=usable_models(merge_models(specs, config)), source="api")


@router.post("/forget", status_code=204)
async def forget_key(
    request: Request, session: SessionDep, x_session_token: str | None = Header(default=None)
) -> Response:
    if x_session_token:
        await _key_store(request).forget_everywhere(session, x_session_token)
    return Response(status_code=204)
