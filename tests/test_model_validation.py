import sys
import types

from core.agent.loop import _validate_model_id


def _fake_litellm(models_by_provider: dict[str, list[str]]) -> types.ModuleType:
    module = types.ModuleType("litellm")
    module.models_by_provider = models_by_provider
    return module


def test_validate_model_id_allows_openrouter_models_not_in_static_catalog(monkeypatch) -> None:
    monkeypatch.setitem(
        sys.modules,
        "litellm",
        _fake_litellm({"openrouter": ["anthropic/claude-sonnet-4-5-20250929"]}),
    )

    ok, err = _validate_model_id("openrouter/anthropic/claude-sonnet-4.6")
    assert ok is True
    assert err is None


def test_validate_model_id_rejects_malformed_openrouter_model() -> None:
    ok, err = _validate_model_id("openrouter/claude-sonnet-4.6")
    assert ok is False
    assert err is not None
    assert "openrouter/<vendor>/<model>" in err


def test_validate_model_id_keeps_strict_checks_for_non_gateway(monkeypatch) -> None:
    monkeypatch.setitem(
        sys.modules,
        "litellm",
        _fake_litellm({"openai": ["gpt-4o-mini"]}),
    )

    ok_valid, err_valid = _validate_model_id("openai/gpt-4o-mini")
    assert ok_valid is True
    assert err_valid is None

    ok_invalid, err_invalid = _validate_model_id("openai/not-a-real-model")
    assert ok_invalid is False
    assert err_invalid is not None
