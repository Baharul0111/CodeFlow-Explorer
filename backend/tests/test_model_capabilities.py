"""Reading model capabilities off the Models API response.

The SDK returns ``capabilities`` as typed objects; the REST docs show nested dicts; older SDKs omit
the field. Getting this wrong once emptied the model dropdown entirely ("No usable models are
available for this key"), so all three shapes are pinned here.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app.config import Settings
from app.llm.catalog import merge_models, pick_deep_model, pick_default_model, usable_models
from app.llm.client import model_spec_from_info
from app.llm.types import ModelSpec


def _support(value: bool) -> SimpleNamespace:
    return SimpleNamespace(supported=value)


def typed_info(model_id: str, *, structured: bool = True, effort: bool = True) -> Any:
    """Mirrors what anthropic's SDK actually hands back: nested Pydantic-style objects."""
    return SimpleNamespace(
        id=model_id,
        display_name=model_id.replace("claude-", "Claude ").title(),
        max_input_tokens=1_000_000,
        max_tokens=128_000,
        capabilities=SimpleNamespace(
            batch=_support(True),
            structured_outputs=_support(structured),
            effort=SimpleNamespace(supported=effort, low=_support(effort), high=_support(effort)),
            thinking=SimpleNamespace(
                supported=True,
                types=SimpleNamespace(adaptive=_support(True), enabled=_support(False)),
            ),
        ),
    )


def dict_info(model_id: str, *, structured: bool = True, effort: bool = True) -> Any:
    """Mirrors the shape shown in the REST documentation."""
    return SimpleNamespace(
        id=model_id,
        display_name=model_id,
        max_input_tokens=200_000,
        max_tokens=64_000,
        capabilities={
            "structured_outputs": {"supported": structured},
            "effort": {"supported": effort},
        },
    )


def test_typed_capabilities_are_read() -> None:
    spec = model_spec_from_info(typed_info("claude-opus-5"))
    assert spec.supports_structured_outputs is True
    assert spec.supports_effort is True
    assert spec.max_input_tokens == 1_000_000
    assert spec.source == "api"


def test_dict_capabilities_are_read() -> None:
    spec = model_spec_from_info(dict_info("claude-sonnet-5"))
    assert spec.supports_structured_outputs is True
    assert spec.supports_effort is True


@pytest.mark.parametrize("builder", [typed_info, dict_info])
def test_unsupported_capabilities_are_respected(builder: Any) -> None:
    spec = model_spec_from_info(builder("old-model", structured=False, effort=False))
    assert spec.supports_structured_outputs is False
    assert spec.supports_effort is False


def test_missing_capabilities_fail_open_for_structured_outputs() -> None:
    """An SDK that doesn't report capabilities must not hide every model from the user."""
    bare = SimpleNamespace(
        id="mystery", display_name="Mystery", max_input_tokens=None, max_tokens=None
    )
    spec = model_spec_from_info(bare)
    assert spec.supports_structured_outputs is True  # usable until proven otherwise
    assert spec.supports_effort is False  # sending effort blindly would be a 400


def test_usable_models_never_returns_an_empty_dropdown() -> None:
    models = [ModelSpec(id="a", display_name="A", supports_structured_outputs=False)]
    assert [m.id for m in usable_models(models)] == ["a"]
    assert usable_models([]) == []


def test_real_world_model_list_orders_and_defaults_sensibly(settings: Settings) -> None:
    """The order the live API returned on 2026-09-17, with 11 models on one account."""
    api_order = [
        "claude-fable-5-1",
        "claude-opus-5",
        "claude-sonnet-5",
        "claude-fable-5",
        "claude-opus-4-8",
        "claude-opus-4-7",
        "claude-sonnet-4-6",
        "claude-opus-4-6",
        "claude-opus-4-5-20251101",
        "claude-haiku-4-5-20251001",
        "claude-sonnet-4-5-20250929",
    ]
    merged = merge_models(
        [model_spec_from_info(typed_info(m)) for m in api_order], settings.load_models_config()
    )
    assert len(usable_models(merged)) == 11, "every current model must be offered"

    tiers = [m.tier for m in merged]
    assert tiers == sorted(tiers, key=lambda t: {"capable": 0, "balanced": 1, "cheap": 2}[t])
    # Within a tier the API's order survives, so a successor is never listed below what it replaced.
    capable = [m.id for m in merged if m.tier == "capable"]
    assert capable.index("claude-fable-5-1") < capable.index("claude-fable-5")
    assert capable.index("claude-opus-5") < capable.index("claude-opus-4-8")

    # Best value in the strongest tier — not the priciest model on the account.
    assert pick_default_model(merged) == "claude-opus-5"
    assert pick_deep_model(merged, "claude-opus-5") == "claude-haiku-4-5-20251001"
