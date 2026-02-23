from __future__ import annotations

import pytest

from core.agent.tier_router import TierRouter
from core.config import TierRouterConfig


def _build_router() -> TierRouter:
    cfg = TierRouterConfig(
        enabled=True,
        tiers={
            "light": {"model": "openai/gpt-4.1-mini"},
            "medium": {"model": "openai/gpt-4.1-mini"},
            "heavy": {"model": "openai/gpt-4.1"},
        },
    )
    return TierRouter(cfg, default_model="openai/gpt-4.1-mini")


def test_routes_heavy_keyword_to_heavy_tier() -> None:
    router = _build_router()
    tier, cleaned, model = router.route("please help debug this code path")
    assert tier == "heavy"
    assert model == "openai/gpt-4.1"
    assert cleaned == "please help debug this code path"


def test_routes_medium_keyword_to_medium_tier() -> None:
    router = _build_router()
    tier, _, model = router.route("can you explain this")
    assert tier == "medium"
    assert model == "openai/gpt-4.1-mini"


def test_routes_short_prompt_to_light_tier() -> None:
    router = _build_router()
    tier, _, model = router.route("hey there")
    assert tier == "light"
    assert model == "openai/gpt-4.1-mini"


def test_tier_override_forces_tier_and_strips_prefix() -> None:
    router = _build_router()
    tier, cleaned, model = router.route("!tier heavy write a rust binary")
    assert tier == "heavy"
    assert model == "openai/gpt-4.1"
    assert cleaned == "write a rust binary"


def test_unknown_input_defaults_to_medium_tier() -> None:
    router = _build_router()
    message = (
        "Please share thoughts about the migration plan for next quarter "
        "and potential risks for launch readiness"
    )
    tier, cleaned, model = router.route(message)
    assert tier == "medium"
    assert cleaned == message
    assert model == "openai/gpt-4.1-mini"


def test_invalid_tier_override_raises_usage_error() -> None:
    router = _build_router()
    with pytest.raises(ValueError, match="Usage: !tier <light\\|medium\\|heavy> <message>"):
        router.route("!tier")
