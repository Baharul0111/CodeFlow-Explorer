"""Model catalogue: live list from the Models API merged with local prices and tier hints.

No model id is hardcoded in logic — tiers and prices are matched by id prefix from
``config/models.json``, and the "cheap model for deep levels" choice is made by price.
"""

from __future__ import annotations

from app.config import ModelsConfig
from app.llm.types import ModelSpec


def _apply_pricing(spec: ModelSpec, config: ModelsConfig) -> ModelSpec:
    price = config.price_for(spec.id)
    if price is not None:
        spec.tier = price.tier
        spec.input_price = price.input
        spec.output_price = price.output
        spec.cache_read_price = price.cache_read
        spec.cache_write_price = price.cache_write_5m
    spec.hint = config.tier_hints.get(spec.tier, "")
    return spec


def fallback_models(config: ModelsConfig) -> list[ModelSpec]:
    return [
        _apply_pricing(ModelSpec(id=m.id, display_name=m.display_name, source="fallback"), config)
        for m in config.fallback_models
    ]


def merge_models(api_models: list[ModelSpec], config: ModelsConfig) -> list[ModelSpec]:
    """Price and sort the live list: capable first, then balanced, then cheap."""
    order = {"capable": 0, "balanced": 1, "cheap": 2, "unknown": 3}
    priced = [_apply_pricing(m, config) for m in api_models]
    return sorted(priced, key=lambda m: (order.get(m.tier, 3), -(m.input_price or 0), m.id))


def usable_models(models: list[ModelSpec]) -> list[ModelSpec]:
    return [m for m in models if m.supports_structured_outputs]


def pick_deep_model(models: list[ModelSpec], selected_id: str) -> str:
    """Cheapest usable model for deep levels; falls back to the selected model."""
    candidates = [m for m in usable_models(models) if m.input_price is not None]
    if not candidates:
        return selected_id
    cheapest = min(candidates, key=lambda m: (m.input_price or 0.0, m.output_price or 0.0))
    selected = next((m for m in models if m.id == selected_id), None)
    if selected is not None and (selected.input_price or 0.0) <= (cheapest.input_price or 0.0):
        return selected_id
    return cheapest.id


def find(models: list[ModelSpec], model_id: str) -> ModelSpec | None:
    return next((m for m in models if m.id == model_id), None)
