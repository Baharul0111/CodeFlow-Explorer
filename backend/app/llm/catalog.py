"""Model catalogue: live list from the Models API merged with local prices and tier hints.

No model id is hardcoded in logic — tiers and prices are matched by id prefix from
``config/models.json``, and the "cheap model for deep levels" choice is made by price.
"""

from __future__ import annotations

from app.config import ModelsConfig
from app.llm.types import ModelSpec
from app.logging_setup import get_logger

log = get_logger(__name__)


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


TIER_ORDER = {"capable": 0, "balanced": 1, "cheap": 2, "unknown": 3}


def merge_models(api_models: list[ModelSpec], config: ModelsConfig) -> list[ModelSpec]:
    """Price and group the live list: capable first, then balanced, then cheap.

    Within a tier the Models API's own order is kept (newest first), so a superseded model never
    sorts above its successor.
    """
    priced = [_apply_pricing(m, config) for m in api_models]
    return sorted(priced, key=lambda m: TIER_ORDER.get(m.tier, 3))  # stable: API order preserved


def pick_default_model(models: list[ModelSpec]) -> str | None:
    """The model pre-selected in the dropdown.

    The best value in the strongest tier available: cheapest input price among the top tier, with
    the newest model winning a tie. That keeps the default strong without defaulting to the most
    expensive model on the account, and involves no hardcoded model id.
    """
    usable = usable_models(models)
    if not usable:
        return None
    best_tier = min(TIER_ORDER.get(m.tier, 3) for m in usable)
    candidates = [m for m in usable if TIER_ORDER.get(m.tier, 3) == best_tier]
    return min(candidates, key=lambda m: m.input_price if m.input_price is not None else 0.0).id


def usable_models(models: list[ModelSpec]) -> list[ModelSpec]:
    """Models this app can drive.

    If the capability data would filter everything out, keep the full list instead: a wrong model
    fails with a clear message at call time, whereas an empty dropdown leaves the user stuck.
    """
    usable = [m for m in models if m.supports_structured_outputs]
    if not usable and models:
        log.warning("no_model_reported_structured_outputs", count=len(models))
        return models
    return usable


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
