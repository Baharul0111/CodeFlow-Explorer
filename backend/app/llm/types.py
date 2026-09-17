"""Shared value objects for the LLM layer."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel

Task = Literal[
    "function_summary",
    "file_summary",
    "module_summary",
    "system_flow",
    "expand",
    "steps",
    "repair",
    "ping",
]


@dataclass(frozen=True, slots=True)
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_write_tokens: int = 0
    cache_read_tokens: int = 0

    def __add__(self, other: TokenUsage) -> TokenUsage:
        return TokenUsage(
            self.input_tokens + other.input_tokens,
            self.output_tokens + other.output_tokens,
            self.cache_write_tokens + other.cache_write_tokens,
            self.cache_read_tokens + other.cache_read_tokens,
        )

    @property
    def total(self) -> int:
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_write_tokens
            + self.cache_read_tokens
        )


@dataclass(slots=True)
class LlmResult:
    data: dict[str, Any]
    model: str
    usage: TokenUsage = field(default_factory=TokenUsage)
    cached: bool = False
    attempts: int = 1


class ModelSpec(BaseModel):
    """A model offered in the UI dropdown."""

    id: str
    display_name: str
    tier: str = "unknown"
    hint: str = ""
    supports_structured_outputs: bool = True
    supports_effort: bool = False
    max_input_tokens: int | None = None
    max_output_tokens: int | None = None
    input_price: float | None = None
    output_price: float | None = None
    cache_read_price: float | None = None
    cache_write_price: float | None = None
    source: Literal["api", "fallback"] = "fallback"


@dataclass(frozen=True, slots=True)
class SystemBlock:
    """One block of the system prompt. ``cache`` marks a prompt-caching breakpoint."""

    text: str
    cache: bool = False
