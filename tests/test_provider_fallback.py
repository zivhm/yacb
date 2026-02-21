from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

import core.providers.litellm_provider as lp
from core.agent.router import AgentRouter
from core.bus.queue import MessageBus
from core.config import Config
from core.providers.litellm_provider import LiteLLMProvider
from core.providers.registry import normalize_model_name


class MockProviderError(Exception):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


def _mock_completion_response(content: str = "ok") -> SimpleNamespace:
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=content, tool_calls=None),
                finish_reason="stop",
            )
        ],
        usage=SimpleNamespace(prompt_tokens=3, completion_tokens=2, total_tokens=5),
    )


def test_normalize_model_name_aliases_and_prefixes() -> None:
    assert normalize_model_name("haiku") == "anthropic/claude-haiku-4-20250514"
    assert normalize_model_name("gpt-4o-mini") == "openai/gpt-4o-mini"
    assert normalize_model_name("qwen3-coder") == "opencode/qwen3-coder"
    assert (
        normalize_model_name("anthropic/claude-sonnet-4-20250514")
        == "anthropic/claude-sonnet-4-20250514"
    )


def test_config_provider_resolution_supports_aliases() -> None:
    cfg = Config()
    cfg.providers.anthropic.api_key = "ant-test"
    cfg.providers.openai.api_key = "oa-test"
    cfg.providers.opencode.api_key = "oc-test"

    _, provider_name = cfg.get_provider("haiku")
    assert provider_name == "anthropic"
    _, provider_name = cfg.get_provider("qwen3-coder")
    assert provider_name == "opencode"


def test_provider_seeds_known_provider_env_keys(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENCODE_API_KEY", raising=False)

    LiteLLMProvider(
        default_model="anthropic/claude-sonnet-4-20250514",
        provider_api_keys={
            "openai": "oa-test",
            "anthropic": "ant-test",
            "opencode": "oc-test",
        },
    )

    assert os.environ.get("OPENAI_API_KEY") == "oa-test"
    assert os.environ.get("ANTHROPIC_API_KEY") == "ant-test"
    assert os.environ.get("OPENCODE_API_KEY") == "oc-test"


def test_opencode_model_is_translated_to_openai_for_litellm() -> None:
    provider = LiteLLMProvider(
        default_model="opencode/qwen3-coder",
        provider_name="opencode",
        api_base="https://opencode.ai/zen/v1",
    )

    assert provider._resolve_model("opencode/qwen3-coder") == "openai/qwen3-coder"


def test_router_uses_default_api_base_for_opencode_provider(tmp_path) -> None:
    cfg = Config()
    cfg.providers.opencode.api_key = "oc-test"
    cfg.agents["default"].model = "opencode/qwen3-coder"
    cfg.agents["default"].workspace = str(tmp_path / "agent")

    router = AgentRouter(config=cfg, bus=MessageBus())
    provider = router._get_provider(cfg.agents["default"])

    assert provider.api_base == "https://opencode.ai/zen/v1"


@pytest.mark.asyncio
async def test_chat_retries_on_transient_error_and_uses_fallback(monkeypatch) -> None:
    calls: list[str] = []

    async def fake_acompletion(**kwargs):
        model = kwargs["model"]
        calls.append(model)
        if len(calls) == 1:
            raise MockProviderError("rate limit", status_code=429)
        return _mock_completion_response("fallback-ok")

    monkeypatch.setattr(lp, "acompletion", fake_acompletion)

    provider = LiteLLMProvider(
        default_model="gpt-4.1-mini",
        fallback_models=["gpt-4o-mini"],
        fallback_max_attempts=2,
    )
    response = await provider.chat(messages=[{"role": "user", "content": "hi"}])

    assert response.content == "fallback-ok"
    assert calls == ["openai/gpt-4.1-mini", "openai/gpt-4o-mini"]


@pytest.mark.asyncio
async def test_chat_uses_default_model_as_first_fallback_when_requested_model_fails(monkeypatch) -> None:
    calls: list[str] = []

    async def fake_acompletion(**kwargs):
        model = kwargs["model"]
        calls.append(model)
        if len(calls) == 1:
            raise MockProviderError("service unavailable", status_code=503)
        return _mock_completion_response("default-ok")

    monkeypatch.setattr(lp, "acompletion", fake_acompletion)

    provider = LiteLLMProvider(
        default_model="openai/gpt-4o-mini",
        fallback_max_attempts=2,
    )
    response = await provider.chat(
        messages=[{"role": "user", "content": "hi"}],
        model="openai/gpt-4.1-mini",
    )

    assert response.content == "default-ok"
    assert calls == ["openai/gpt-4.1-mini", "openai/gpt-4o-mini"]


@pytest.mark.asyncio
async def test_chat_does_not_retry_on_non_retryable_error(monkeypatch) -> None:
    calls: list[str] = []

    async def fake_acompletion(**kwargs):
        calls.append(kwargs["model"])
        raise MockProviderError("invalid api key", status_code=401)

    monkeypatch.setattr(lp, "acompletion", fake_acompletion)

    provider = LiteLLMProvider(
        default_model="openai/gpt-4.1-mini",
        fallback_models=["gpt-4o-mini"],
        fallback_max_attempts=2,
    )
    response = await provider.chat(messages=[{"role": "user", "content": "hi"}])

    assert response.finish_reason == "error"
    assert "invalid api key" in (response.content or "").lower()
    assert calls == ["openai/gpt-4.1-mini"]


@pytest.mark.asyncio
async def test_chat_handles_empty_choices_without_crashing(monkeypatch) -> None:
    async def fake_acompletion(**kwargs):
        return SimpleNamespace(choices=[], usage=None)

    monkeypatch.setattr(lp, "acompletion", fake_acompletion)

    provider = LiteLLMProvider(default_model="openai/gpt-4.1-mini")
    response = await provider.chat(messages=[{"role": "user", "content": "hi"}])

    assert response.finish_reason == "stop"
    assert response.content == ""
