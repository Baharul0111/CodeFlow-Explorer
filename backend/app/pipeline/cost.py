"""Token accounting and USD cost."""

from __future__ import annotations

from dataclasses import dataclass

from app.llm.types import ModelSpec, TokenUsage

PER_MILLION = 1_000_000.0


def cost_usd(usage: TokenUsage, spec: ModelSpec | None) -> float:
    if spec is None or spec.input_price is None or spec.output_price is None:
        return 0.0
    cache_read = (
        spec.cache_read_price if spec.cache_read_price is not None else spec.input_price * 0.1
    )
    cache_write = (
        spec.cache_write_price if spec.cache_write_price is not None else spec.input_price * 1.25
    )
    return (
        usage.input_tokens * spec.input_price
        + usage.output_tokens * spec.output_price
        + usage.cache_read_tokens * cache_read
        + usage.cache_write_tokens * cache_write
    ) / PER_MILLION


@dataclass(slots=True)
class CostTotals:
    usage: TokenUsage
    cost_usd: float = 0.0
    calls: int = 0
    cached_calls: int = 0

    def add(self, usage: TokenUsage, spec: ModelSpec | None, *, cached: bool = False) -> None:
        self.usage = self.usage + usage
        self.calls += 1
        if cached:
            self.cached_calls += 1
        else:
            self.cost_usd += cost_usd(usage, spec)

    def as_dict(self) -> dict[str, float | int]:
        return {
            "input_tokens": self.usage.input_tokens,
            "output_tokens": self.usage.output_tokens,
            "cache_write_tokens": self.usage.cache_write_tokens,
            "cache_read_tokens": self.usage.cache_read_tokens,
            "cost_usd": round(self.cost_usd, 6),
            "calls": self.calls,
            "cached_calls": self.cached_calls,
        }


def empty_totals() -> CostTotals:
    return CostTotals(usage=TokenUsage())
