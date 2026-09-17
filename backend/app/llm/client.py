"""``ClaudeClient`` protocol and the real Anthropic implementation.

Design notes
------------
* Structured outputs (``output_config.format``) are used for every call, so responses are JSON with
  no prose and no tool-use system-prompt overhead.
* Prompt caching: system blocks marked ``cache=True`` get ``cache_control``; the stable global
  block comes first, then the project block, then the per-call user text (never cached).
* Retries are implemented here (SDK retries are disabled) so back-off, jitter, ``retry-after`` and
  logging are explicit and testable.
* ``effort``/``thinking`` are only sent when the model's capability flags allow them.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import random
from collections.abc import Awaitable, Callable, Iterator
from typing import Any, Protocol, TypeVar, runtime_checkable

import anthropic
from anthropic.types import Message, ModelInfo, TextBlockParam

from app.llm.errors import (
    SPEND_LIMIT,
    BadOutputError,
    ConnectionFailedError,
    InvalidKeyError,
    LlmError,
    ModelUnavailableError,
    NoCreditsError,
    OverloadedError,
    RateLimitedError,
    RefusalError,
)
from app.llm.types import LlmResult, ModelSpec, SystemBlock, Task, TokenUsage
from app.logging_setup import get_logger, redact

log = get_logger(__name__)
T = TypeVar("T")

MAX_ATTEMPTS = 4
BASE_DELAY = 1.0
MAX_DELAY = 30.0
PING_MAX_TOKENS = 1


@contextlib.contextmanager
def llm_errors() -> Iterator[None]:
    """Map anything raised while talking to Claude to a plain-English :class:`LlmError`.

    The client maps its own failures, but this guard means a surprise from the SDK (or from a
    stubbed client in tests) can never reach the user as an opaque 500.
    """
    try:
        yield
    except Exception as exc:
        raise map_api_error(exc) from exc


@runtime_checkable
class ClaudeClient(Protocol):
    """Everything the pipeline needs from Claude. Implemented by the real and mock clients."""

    async def generate_json(
        self,
        *,
        task: Task,
        system: list[SystemBlock],
        user_text: str,
        schema: dict[str, Any],
        model: str,
        max_tokens: int,
        effort: str | None = None,
    ) -> LlmResult: ...

    async def count_tokens(
        self, *, system: list[SystemBlock], user_text: str, model: str
    ) -> int: ...

    async def list_models(self) -> list[ModelSpec]: ...

    async def verify_credentials(self, *, model: str | None = None) -> None: ...

    async def aclose(self) -> None: ...


def _capability(info: ModelInfo, *path: str) -> bool:
    node: Any = getattr(info, "capabilities", None)
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return False
        node = node[key]
    if isinstance(node, dict):
        return bool(node.get("supported", False))
    return bool(node)


def model_spec_from_info(info: ModelInfo) -> ModelSpec:
    return ModelSpec(
        id=info.id,
        display_name=info.display_name or info.id,
        supports_structured_outputs=_capability(info, "structured_outputs"),
        supports_effort=_capability(info, "effort"),
        max_input_tokens=getattr(info, "max_input_tokens", None),
        max_output_tokens=getattr(info, "max_tokens", None),
        source="api",
    )


def _usage_of(message: Message) -> TokenUsage:
    usage = message.usage
    return TokenUsage(
        input_tokens=usage.input_tokens or 0,
        output_tokens=usage.output_tokens or 0,
        cache_write_tokens=usage.cache_creation_input_tokens or 0,
        cache_read_tokens=usage.cache_read_input_tokens or 0,
    )


def _retry_after(exc: anthropic.APIStatusError) -> float | None:
    response = getattr(exc, "response", None)
    header = response.headers.get("retry-after") if response is not None else None
    try:
        return float(header) if header else None
    except ValueError:
        return None


def map_api_error(exc: Exception) -> LlmError:  # noqa: PLR0911, PLR0912 - one per error class
    """Translate an SDK exception into a plain-English :class:`LlmError`."""
    if isinstance(exc, LlmError):
        return exc
    if isinstance(exc, anthropic.AuthenticationError):
        return InvalidKeyError()
    if isinstance(exc, anthropic.PermissionDeniedError):
        return ModelUnavailableError()
    if isinstance(exc, anthropic.NotFoundError):
        return ModelUnavailableError()
    if isinstance(exc, anthropic.RateLimitError):
        after = _retry_after(exc)
        if after is None and "spend" in str(getattr(exc, "message", "")).lower():
            return LlmError(SPEND_LIMIT, code="spend_limit", status_code=429)
        return RateLimitedError(retry_after=after)
    if isinstance(exc, anthropic.APIConnectionError | anthropic.APITimeoutError):
        return ConnectionFailedError()
    if isinstance(exc, anthropic.APIStatusError):
        status = exc.status_code
        if status == 402:
            return NoCreditsError()
        if status == 413:
            return LlmError(
                "This part of the code is too big to send in one go.",
                code="too_large",
                status_code=413,
            )
        if status in (429, 529) or status >= 500:
            return OverloadedError(retry_after=_retry_after(exc))
        message = redact(str(getattr(exc, "message", "")) or "Claude rejected the request.")
        lowered = message.lower()
        if "credit" in lowered or "billing" in lowered:
            return NoCreditsError()
        if "model" in lowered and ("not" in lowered or "access" in lowered):
            return ModelUnavailableError()
        return LlmError(
            f"Claude rejected the request: {message}", code="bad_request", status_code=400
        )
    return LlmError(redact(f"Unexpected problem talking to Claude: {exc}"), code="llm_error")


class AnthropicClaudeClient:
    """Real client. The API key lives only in this object (and the SDK it wraps)."""

    def __init__(
        self,
        api_key: str,
        *,
        timeout: float = 240.0,
        max_attempts: int = MAX_ATTEMPTS,
        sleep: Any = asyncio.sleep,
    ) -> None:
        # max_retries=0: retrying is handled below so back-off and logging stay explicit.
        self._client = anthropic.AsyncAnthropic(api_key=api_key, timeout=timeout, max_retries=0)
        self._max_attempts = max_attempts
        self._sleep = sleep

    async def aclose(self) -> None:
        await self._client.close()

    # ------------------------------------------------------------------ calls
    def _build_system(self, blocks: list[SystemBlock]) -> list[TextBlockParam]:
        out: list[TextBlockParam] = []
        for block in blocks:
            if not block.text.strip():
                continue
            entry: TextBlockParam = {"type": "text", "text": block.text}
            if block.cache:
                entry["cache_control"] = {"type": "ephemeral"}
            out.append(entry)
        return out

    async def _with_retries(self, what: Task, fn: Callable[[], Awaitable[T]]) -> T:
        last: LlmError | None = None
        for attempt in range(1, self._max_attempts + 1):
            try:
                return await fn()
            except Exception as exc:  # mapped below; nothing raw escapes
                error = map_api_error(exc)
                last = error
                if not error.retryable or attempt == self._max_attempts:
                    raise error from exc
                delay = min(BASE_DELAY * 2 ** (attempt - 1), MAX_DELAY)
                if error.retry_after:
                    delay = max(delay, error.retry_after)
                delay += random.uniform(0, 0.5)  # noqa: S311 - jitter, not cryptography
                log.warning(
                    "llm_retry",
                    task=what,
                    attempt=attempt,
                    delay=round(delay, 2),
                    reason=error.code,
                )
                await self._sleep(delay)
        raise last or LlmError("Claude could not be reached.")

    async def generate_json(
        self,
        *,
        task: Task,
        system: list[SystemBlock],
        user_text: str,
        schema: dict[str, Any],
        model: str,
        max_tokens: int,
        effort: str | None = None,
    ) -> LlmResult:
        params: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "system": self._build_system(system),
            "messages": [{"role": "user", "content": user_text}],
            "output_config": {"format": {"type": "json_schema", "schema": schema}},
        }
        if effort:
            params["output_config"]["effort"] = effort

        async def call() -> Message:
            created: Message = await self._client.messages.create(**params)
            return created

        message = await self._with_retries(task, call)
        if message.stop_reason == "refusal":
            raise RefusalError()
        if message.stop_reason == "max_tokens":
            params["max_tokens"] = min(max_tokens * 2, 32_000)
            message = await self._with_retries(task, call)
            if message.stop_reason == "max_tokens":
                raise BadOutputError(
                    "Claude's answer was cut short. Try a smaller part of the code."
                )
        text = next((b.text for b in message.content if b.type == "text"), "")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise BadOutputError() from exc
        if not isinstance(data, dict):
            raise BadOutputError()
        return LlmResult(data=data, model=message.model, usage=_usage_of(message))

    async def count_tokens(self, *, system: list[SystemBlock], user_text: str, model: str) -> int:
        async def call() -> int:
            counted = await self._client.messages.count_tokens(
                model=model,
                system=self._build_system(system),
                messages=[{"role": "user", "content": user_text}],
            )
            return int(counted.input_tokens)

        return await self._with_retries("ping", call)

    # ----------------------------------------------------------------- models
    async def list_models(self) -> list[ModelSpec]:
        async def call() -> list[ModelSpec]:
            specs: list[ModelSpec] = []
            async for info in self._client.models.list():
                specs.append(model_spec_from_info(info))
            return specs

        return await self._with_retries("ping", call)

    async def verify_credentials(self, *, model: str | None = None) -> None:
        """Check the key works and the account can actually spend.

        ``models.list`` proves the key is valid but not that there are credits, so a 1-token
        message is sent on the cheapest available model (costs a fraction of a cent).
        """
        await self.list_models()
        if model is None:
            return

        async def ping() -> Message:
            return await self._client.messages.create(
                model=model,
                max_tokens=PING_MAX_TOKENS,
                messages=[{"role": "user", "content": "hi"}],
            )

        await self._with_retries("ping", ping)
