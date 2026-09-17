from __future__ import annotations

from app.config import Settings
from app.llm.catalog import fallback_models, find, merge_models, pick_deep_model, usable_models
from app.llm.types import ModelSpec, TokenUsage
from app.pipeline.cost import cost_usd, empty_totals


def _config(settings: Settings):  # type: ignore[no-untyped-def]
    return settings.load_models_config()


def test_fallback_models_are_priced(settings: Settings) -> None:
    models = fallback_models(_config(settings))
    assert [m.id for m in models]
    top = models[0]
    assert top.input_price and top.output_price and top.hint


def test_merge_sorts_capable_first_and_prices_by_prefix(settings: Settings) -> None:
    api = [
        ModelSpec(id="claude-haiku-4-5", display_name="H", source="api"),
        ModelSpec(id="claude-opus-5", display_name="O", source="api"),
        ModelSpec(id="claude-sonnet-5", display_name="S", source="api"),
    ]
    merged = merge_models(api, _config(settings))
    assert [m.id for m in merged] == ["claude-opus-5", "claude-sonnet-5", "claude-haiku-4-5"]
    assert find(merged, "claude-opus-5").input_price == 5.0  # type: ignore[union-attr]
    assert find(merged, "claude-sonnet-5").input_price == 2.0  # type: ignore[union-attr]
    assert find(merged, "claude-haiku-4-5").hint == "Fastest and cheapest"  # type: ignore[union-attr]


def test_longest_prefix_wins(settings: Settings) -> None:
    merged = merge_models([ModelSpec(id="claude-fable-5-1", display_name="F")], _config(settings))
    assert merged[0].cache_read_price == 0.25  # the fable-5-1 row, not the generic fable row


def test_models_without_structured_outputs_are_filtered() -> None:
    models = [
        ModelSpec(id="a", display_name="A", supports_structured_outputs=True),
        ModelSpec(id="b", display_name="B", supports_structured_outputs=False),
    ]
    assert [m.id for m in usable_models(models)] == ["a"]


def test_pick_deep_model_prefers_the_cheapest(settings: Settings) -> None:
    merged = merge_models(
        [
            ModelSpec(id="claude-opus-5", display_name="O"),
            ModelSpec(id="claude-haiku-4-5", display_name="H"),
        ],
        _config(settings),
    )
    assert pick_deep_model(merged, "claude-opus-5") == "claude-haiku-4-5"
    # already the cheapest: keep it
    assert pick_deep_model(merged, "claude-haiku-4-5") == "claude-haiku-4-5"


def test_cost_uses_every_token_class() -> None:
    spec = ModelSpec(
        id="m",
        display_name="M",
        input_price=5.0,
        output_price=25.0,
        cache_read_price=0.5,
        cache_write_price=6.25,
    )
    usage = TokenUsage(
        input_tokens=1_000_000,
        output_tokens=1_000_000,
        cache_read_tokens=1_000_000,
        cache_write_tokens=1_000_000,
    )
    assert cost_usd(usage, spec) == 5.0 + 25.0 + 0.5 + 6.25
    assert cost_usd(usage, None) == 0.0


def test_totals_skip_cost_for_cached_calls() -> None:
    spec = ModelSpec(id="m", display_name="M", input_price=5.0, output_price=25.0)
    totals = empty_totals()
    totals.add(TokenUsage(input_tokens=1_000_000), spec)
    totals.add(TokenUsage(input_tokens=1_000_000), spec, cached=True)
    assert totals.calls == 2 and totals.cached_calls == 1
    assert totals.as_dict()["cost_usd"] == 5.0
