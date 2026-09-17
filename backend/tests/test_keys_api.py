from __future__ import annotations

import anthropic
import httpx
import pytest
from httpx import AsyncClient

from app.config import Settings
from app.llm.keystore import KeyStore
from app.llm.types import ModelSpec

KEY = "sk-ant-api03-testkey-0123456789"


async def test_mock_mode_test_key_returns_models_not_the_key(client: AsyncClient) -> None:
    resp = await client.post("/api/keys/test", json={"api_key": KEY})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert KEY not in resp.text
    assert body["key_fingerprint"] == KEY[-4:]
    assert [m["id"] for m in body["models"]] == ["mock-capable", "mock-cheap"]
    assert body["suggested_model"] == "mock-capable"
    assert body["suggested_deep_model"] == "mock-cheap"
    assert body["models"][0]["hint"] == "Most capable"

    models = await client.get(
        "/api/keys/models", headers={"X-Session-Token": body["session_token"]}
    )
    assert models.status_code == 200
    assert models.json()["source"] == "api"

    forget = await client.post(
        "/api/keys/forget", headers={"X-Session-Token": body["session_token"]}
    )
    assert forget.status_code == 204


async def test_models_without_a_key_serve_the_fallback_list(
    client: AsyncClient, settings: Settings
) -> None:
    settings.llm_mode = "anthropic"
    resp = await client.get("/api/keys/models")
    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] == "fallback"
    assert [m["id"] for m in body["models"]] == [
        "claude-opus-5",
        "claude-sonnet-5",
        "claude-haiku-4-5",
    ]
    assert all(m["input_price"] for m in body["models"])


def _error(status: int, message: str) -> anthropic.APIStatusError:
    response = httpx.Response(
        status,
        json={"type": "error", "error": {"type": "e", "message": message}},
        request=httpx.Request("GET", "https://api.anthropic.com/v1/models"),
    )
    cls = {
        401: anthropic.AuthenticationError,
        403: anthropic.PermissionDeniedError,
        404: anthropic.NotFoundError,
        429: anthropic.RateLimitError,
    }.get(status, anthropic.APIStatusError)
    return cls(message, response=response, body=None)  # type: ignore[call-arg]


@pytest.mark.parametrize(
    ("status", "expected_code", "needle"),
    [
        (401, "invalid_key", "not valid"),
        (402, "no_credits", "no credits"),
        (403, "model_unavailable", "isn't available"),
    ],
)
async def test_real_mode_errors_are_plain_english(
    client: AsyncClient,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    status: int,
    expected_code: str,
    needle: str,
) -> None:
    settings.llm_mode = "anthropic"

    async def boom(self: object) -> list[ModelSpec]:
        raise _error(status, "raw api text")

    monkeypatch.setattr("app.llm.client.AnthropicClaudeClient.list_models", boom)
    resp = await client.post("/api/keys/test", json={"api_key": KEY})
    assert resp.status_code in (401, 402, 404)
    err = resp.json()["error"]
    assert err["code"] == expected_code
    assert needle in err["message"]
    assert KEY not in resp.text


async def test_rate_limit_message(
    client: AsyncClient, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings.llm_mode = "anthropic"

    async def boom(self: object) -> list[ModelSpec]:
        raise _error(429, "slow down")

    monkeypatch.setattr("app.llm.client.AnthropicClaudeClient.list_models", boom)
    resp = await client.post("/api/keys/test", json={"api_key": KEY})
    assert resp.status_code == 429
    assert "Too many requests" in resp.json()["error"]["message"]


async def test_key_never_appears_in_logs(
    client: AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level("DEBUG"):
        await client.post("/api/keys/test", json={"api_key": KEY})
    assert KEY not in caplog.text
    assert "sk-ant-api03-testkey" not in caplog.text


async def test_remembered_key_survives_a_new_store(client: AsyncClient) -> None:
    resp = await client.post("/api/keys/test", json={"api_key": KEY, "remember": True})
    token = resp.json()["session_token"]
    store: KeyStore = client._transport.app.state.key_store  # type: ignore[attr-defined]
    store.forget(token)  # simulate a restart: memory is empty, the encrypted row remains
    models = await client.get("/api/keys/models", headers={"X-Session-Token": token})
    assert models.status_code == 200
    assert KEY not in models.text
