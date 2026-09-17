"""Cost estimate before any analysis runs.

Real ``count_tokens`` calls are made on a small representative sample of prompts, then
extrapolated by the number of calls the pipeline will actually make. Output tokens are estimated
from per-task caps observed in practice.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from pathlib import Path

from app.llm.client import ClaudeClient, llm_errors
from app.llm.prompts import (
    SUMMARY_INSTRUCTION,
    SYSTEM_FLOW_INSTRUCTION,
    global_block,
    render_user_text,
)
from app.llm.types import ModelSpec, SystemBlock, TokenUsage
from app.parsing.codemap import CodeMap
from app.pipeline.cost import cost_usd
from app.pipeline.summaries import MAX_BATCH_ITEMS, read_symbol_code
from app.pipeline.units import top_level_units

SAMPLE_SIZE = 5
OUTPUT_TOKENS_PER_SUMMARY_BATCH = 400
OUTPUT_TOKENS_PER_FLOW = 900
BACKGROUND_EXPANSIONS_FACTOR = 1.4  # stages, then their children, generated up front


@dataclass(slots=True)
class Estimate:
    input_tokens: int
    output_tokens: int
    cached_input_tokens: int
    calls: int
    low_usd: float
    high_usd: float
    top_model: str
    deep_model: str
    over_limit: bool
    limit_usd: float

    def as_dict(self) -> dict[str, float | int | str | bool]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cached_input_tokens": self.cached_input_tokens,
            "calls": self.calls,
            "low_usd": round(self.low_usd, 4),
            "high_usd": round(self.high_usd, 4),
            "top_model": self.top_model,
            "deep_model": self.deep_model,
            "over_limit": self.over_limit,
            "limit_usd": self.limit_usd,
        }


def _sample_symbols(cm: CodeMap, root: Path) -> list[str]:
    functions = [s for s in cm.functions() if not s.is_trivial]
    functions.sort(key=lambda s: s.line_count)
    if not functions:
        return []
    picks = {
        0,
        len(functions) // 4,
        len(functions) // 2,
        (3 * len(functions)) // 4,
        len(functions) - 1,
    }
    samples = []
    for index in sorted(picks)[:SAMPLE_SIZE]:
        code = read_symbol_code(root, functions[index])
        if code:
            samples.append(code)
    return samples


async def estimate_project(
    *,
    client: ClaudeClient,
    cm: CodeMap,
    root: Path,
    project_block: SystemBlock,
    top_model: str,
    deep_model: str,
    top_spec: ModelSpec | None,
    deep_spec: ModelSpec | None,
    limit_usd: float,
) -> Estimate:
    summary_system = [global_block(summaries=True), project_block]
    flow_system = [global_block(), project_block]
    samples = _sample_symbols(cm, root)

    per_symbol_tokens = 0
    with llm_errors():
        if samples:
            counted = []
            for code in samples:
                text = render_user_text(
                    "function_summary", SUMMARY_INSTRUCTION, {"items": [{"id": "x", "code": code}]}
                )
                counted.append(
                    await client.count_tokens(
                        system=summary_system, user_text=text, model=deep_model
                    )
                )
            per_symbol_tokens = int(statistics.median(counted))
        menu, _scope = top_level_units(cm, {})
        flow_text = render_user_text(
            "system_flow", SYSTEM_FLOW_INSTRUCTION, {"units": [u.as_payload() for u in menu]}
        )
        flow_tokens = await client.count_tokens(
            system=flow_system, user_text=flow_text, model=top_model
        )
        system_tokens = await client.count_tokens(
            system=flow_system, user_text="x", model=top_model
        )

    non_trivial = sum(1 for s in cm.functions() if not s.is_trivial)
    summary_batches = max(1, -(-non_trivial // MAX_BATCH_ITEMS))
    file_batches = max(1, -(-len(cm.files) // MAX_BATCH_ITEMS))
    module_batches = max(1, -(-len(cm.modules()) // MAX_BATCH_ITEMS))
    expansions = int(min(len(cm.files) + len(cm.modules()), 60) * BACKGROUND_EXPANSIONS_FACTOR)

    body_per_symbol = max(0, per_symbol_tokens - system_tokens)
    summary_input = summary_batches * (system_tokens + body_per_symbol * MAX_BATCH_ITEMS)
    file_input = (file_batches + module_batches) * (system_tokens + 600)
    flow_input = flow_tokens + expansions * (system_tokens + 700)
    total_input = summary_input + file_input + flow_input
    cached_input = (summary_batches + file_batches + module_batches + expansions) * system_tokens
    calls = summary_batches + file_batches + module_batches + expansions + 1
    output = (summary_batches + file_batches + module_batches) * OUTPUT_TOKENS_PER_SUMMARY_BATCH + (
        expansions + 1
    ) * OUTPUT_TOKENS_PER_FLOW

    deep_share = summary_input
    top_share = max(0, total_input - deep_share)
    low = cost_usd(
        TokenUsage(
            input_tokens=int(top_share * 0.25),
            output_tokens=int(output * 0.5),
            cache_read_tokens=int(cached_input * 0.8),
        ),
        top_spec,
    ) + cost_usd(
        TokenUsage(input_tokens=int(deep_share * 0.6), output_tokens=int(output * 0.3)), deep_spec
    )
    high = cost_usd(
        TokenUsage(input_tokens=top_share, output_tokens=output, cache_write_tokens=cached_input),
        top_spec,
    ) + cost_usd(TokenUsage(input_tokens=deep_share, output_tokens=output), deep_spec)
    return Estimate(
        input_tokens=int(total_input),
        output_tokens=int(output),
        cached_input_tokens=int(cached_input),
        calls=int(calls),
        low_usd=min(low, high),
        high_usd=max(low, high),
        top_model=top_model,
        deep_model=deep_model,
        over_limit=max(low, high) > limit_usd,
        limit_usd=limit_usd,
    )
