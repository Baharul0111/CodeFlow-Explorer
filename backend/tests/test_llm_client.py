from __future__ import annotations

import json
from typing import Any

import anthropic
import httpx
import pytest

from app.llm.client import AnthropicClaudeClient, map_api_error
from app.llm.errors import (
    BAD_OUTPUT,
    INVALID_KEY,
    MODEL_UNAVAILABLE,
    NO_CREDITS,
    OVERLOADED,
    RATE_LIMITED,
    REFUSED,
    BadOutputError,
    ConnectionFailedError,
    LlmError,
    NoCreditsError,
    OverloadedError,
    RateLimitedError,
    RefusalError,
)
from app.llm.schemas import FLOW_SCHEMA
from app.llm.types import SystemBlock


def _response(
    status: int, body: dict[str, Any] | None = None, headers: dict[str, str] | None = None
) -> httpx.Response:
    return httpx.Response(
        status,
        json=body or {"type": "error", "error": {"type": "x", "message": "boom"}},
        headers=headers or {},
        request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"),
    )


def _status_error(
    status: int, message: str = "boom", headers: dict[str, str] | None = None
) -> anthropic.APIStatusError:
    response = _response(
        status, {"type": "error", "error": {"type": "x", "message": message}}, headers
    )
    cls = {
        401: anthropic.AuthenticationError,
        403: anthropic.PermissionDeniedError,
        404: anthropic.NotFoundError,
        429: anthropic.RateLimitError,
    }.get(status, anthropic.APIStatusError)
    return cls(message, response=response, body=None)  # type: ignore[call-arg]


@pytest.mark.parametrize(
    ("status", "expected_message"),
    [
        (401, INVALID_KEY),
        (402, NO_CREDITS),
        (403, MODEL_UNAVAILABLE),
        (404, MODEL_UNAVAILABLE),
        (429, RATE_LIMITED),
        (500, OVERLOADED),
        (529, OVERLOADED),
    ],
)
def test_error_messages_are_plain_english(status: int, expected_message: str) -> None:
    err = map_api_error(_status_error(status))
    assert err.message == expected_message


def test_rate_limit_keeps_retry_after() -> None:
    err = map_api_error(_status_error(429, headers={"retry-after": "7"}))
    assert isinstance(err, RateLimitedError) and err.retry_after == 7.0 and err.retryable


def test_connection_error_mapped() -> None:
    exc = anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com"))
    assert isinstance(map_api_error(exc), ConnectionFailedError)


def test_error_messages_never_leak_keys() -> None:
    err = map_api_error(RuntimeError("failed with key sk-ant-api03-SECRETSECRET1234"))
    assert "sk-ant-api03-SECRETSECRET1234" not in err.message
    assert "REDACTED" in err.message


class _FakeMessages:
    def __init__(self, script: list[Any]) -> None:
        self.script = script
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def count_tokens(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return type("C", (), {"input_tokens": 123})()


class _Msg:
    def __init__(
        self, text: str, *, stop_reason: str = "end_turn", usage: Any = None, model: str = "m"
    ) -> None:
        self.content = [type("B", (), {"type": "text", "text": text})()]
        self.stop_reason = stop_reason
        self.model = model
        self.usage = (
            usage
            or type(
                "U",
                (),
                {
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "cache_creation_input_tokens": 3,
                    "cache_read_input_tokens": 2,
                },
            )()
        )


def _client(script: list[Any], sleeps: list[float] | None = None) -> AnthropicClaudeClient:
    async def fake_sleep(delay: float) -> None:
        (sleeps if sleeps is not None else []).append(delay)

    client = AnthropicClaudeClient("sk-ant-test-key", sleep=fake_sleep)
    client._client.messages = _FakeMessages(script)  # type: ignore[assignment]
    return client


SYSTEM = [SystemBlock("global rules", cache=True), SystemBlock("project context", cache=True)]


async def test_generate_json_parses_and_reports_usage() -> None:
    payload = {"nodes": [], "edges": []}
    client = _client([_Msg(json.dumps(payload))])
    result = await client.generate_json(
        task="expand", system=SYSTEM, user_text="hi", schema=FLOW_SCHEMA, model="m", max_tokens=100
    )
    assert result.data == payload
    assert (result.usage.input_tokens, result.usage.output_tokens) == (10, 5)
    assert (result.usage.cache_write_tokens, result.usage.cache_read_tokens) == (3, 2)
    sent = client._client.messages.calls[0]  # type: ignore[attr-defined]
    assert sent["output_config"]["format"] == {"type": "json_schema", "schema": FLOW_SCHEMA}
    assert sent["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert sent["system"][1]["cache_control"] == {"type": "ephemeral"}
    assert "thinking" not in sent and "temperature" not in sent


async def test_effort_only_sent_when_asked() -> None:
    client = _client([_Msg("{}"), _Msg("{}")])
    await client.generate_json(
        task="expand", system=SYSTEM, user_text="a", schema=FLOW_SCHEMA, model="m", max_tokens=10
    )
    await client.generate_json(
        task="expand",
        system=SYSTEM,
        user_text="a",
        schema=FLOW_SCHEMA,
        model="m",
        max_tokens=10,
        effort="low",
    )
    calls = client._client.messages.calls  # type: ignore[attr-defined]
    assert "effort" not in calls[0]["output_config"]
    assert calls[1]["output_config"]["effort"] == "low"


async def test_retries_with_backoff_then_succeeds() -> None:
    sleeps: list[float] = []
    client = _client(
        [_status_error(529), _status_error(429, headers={"retry-after": "3"}), _Msg("{}")], sleeps
    )
    result = await client.generate_json(
        task="expand", system=SYSTEM, user_text="a", schema=FLOW_SCHEMA, model="m", max_tokens=10
    )
    assert result.data == {}
    assert len(sleeps) == 2
    assert sleeps[0] >= 1.0 and sleeps[1] >= 3.0  # honours retry-after


async def test_non_retryable_error_raises_immediately() -> None:
    sleeps: list[float] = []
    client = _client([_status_error(401)], sleeps)
    with pytest.raises(LlmError) as excinfo:
        await client.generate_json(
            task="expand",
            system=SYSTEM,
            user_text="a",
            schema=FLOW_SCHEMA,
            model="m",
            max_tokens=10,
        )
    assert excinfo.value.message == INVALID_KEY
    assert sleeps == []


async def test_retries_give_up_after_max_attempts() -> None:
    client = _client([_status_error(529)] * 4, [])
    with pytest.raises(OverloadedError):
        await client.generate_json(
            task="expand",
            system=SYSTEM,
            user_text="a",
            schema=FLOW_SCHEMA,
            model="m",
            max_tokens=10,
        )


async def test_refusal_is_reported_clearly() -> None:
    client = _client([_Msg("{}", stop_reason="refusal")])
    with pytest.raises(RefusalError) as excinfo:
        await client.generate_json(
            task="expand",
            system=SYSTEM,
            user_text="a",
            schema=FLOW_SCHEMA,
            model="m",
            max_tokens=10,
        )
    assert excinfo.value.message == REFUSED


async def test_max_tokens_retries_with_a_bigger_cap() -> None:
    client = _client([_Msg("{", stop_reason="max_tokens"), _Msg('{"nodes":[],"edges":[]}')])
    result = await client.generate_json(
        task="expand", system=SYSTEM, user_text="a", schema=FLOW_SCHEMA, model="m", max_tokens=1000
    )
    assert result.data == {"nodes": [], "edges": []}
    calls = client._client.messages.calls  # type: ignore[attr-defined]
    assert calls[1]["max_tokens"] == 2000


async def test_invalid_json_raises_bad_output() -> None:
    client = _client([_Msg("not json")])
    with pytest.raises(BadOutputError) as excinfo:
        await client.generate_json(
            task="expand",
            system=SYSTEM,
            user_text="a",
            schema=FLOW_SCHEMA,
            model="m",
            max_tokens=10,
        )
    assert excinfo.value.message == BAD_OUTPUT


async def test_count_tokens() -> None:
    client = _client([])
    assert await client.count_tokens(system=SYSTEM, user_text="hello", model="m") == 123


def test_no_credits_from_message_text() -> None:
    err = map_api_error(_status_error(400, "your credit balance is too low"))
    assert isinstance(err, NoCreditsError)
