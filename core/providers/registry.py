"""Provider registry - single source of truth for LLM provider metadata."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderSpec:
    name: str
    keywords: tuple[str, ...]
    env_key: str
    display_name: str = ""
    litellm_prefix: str = ""
    skip_prefixes: tuple[str, ...] = ()
    is_gateway: bool = False
    default_api_base: str = ""
    strip_model_prefix: bool = False

    @property
    def label(self) -> str:
        return self.display_name or self.name.title()


PROVIDERS: tuple[ProviderSpec, ...] = (
    ProviderSpec(
        name="openrouter",
        keywords=("openrouter",),
        env_key="OPENROUTER_API_KEY",
        display_name="OpenRouter",
        litellm_prefix="openrouter",
        is_gateway=True,
        default_api_base="https://openrouter.ai/api/v1",
    ),
    ProviderSpec(
        name="opencode",
        keywords=("opencode", "zen"),
        env_key="OPENCODE_API_KEY",
        display_name="OpenCode Zen",
        # OpenCode exposes an OpenAI-compatible API; route through LiteLLM's openai provider.
        litellm_prefix="openai",
        skip_prefixes=("openai/",),
        default_api_base="https://opencode.ai/zen/v1",
        strip_model_prefix=True,
    ),
    ProviderSpec(
        name="anthropic",
        keywords=("anthropic", "claude"),
        env_key="ANTHROPIC_API_KEY",
        display_name="Anthropic",
    ),
    ProviderSpec(
        name="openai",
        keywords=("openai", "gpt"),
        env_key="OPENAI_API_KEY",
        display_name="OpenAI",
    ),
    ProviderSpec(
        name="deepseek",
        keywords=("deepseek",),
        env_key="DEEPSEEK_API_KEY",
        display_name="DeepSeek",
        litellm_prefix="deepseek",
        skip_prefixes=("deepseek/",),
    ),
    ProviderSpec(
        name="gemini",
        keywords=("gemini",),
        env_key="GEMINI_API_KEY",
        display_name="Gemini",
        litellm_prefix="gemini",
        skip_prefixes=("gemini/",),
    ),
)


_MODEL_ALIASES: dict[str, str] = {
    # Anthropic
    "haiku": "anthropic/claude-haiku-4-20250514",
    "sonnet": "anthropic/claude-sonnet-4-20250514",
    "opus": "anthropic/claude-opus-4-20250514",
    "claude-haiku-4": "anthropic/claude-haiku-4-20250514",
    "claude-sonnet-4": "anthropic/claude-sonnet-4-20250514",
    "claude-sonnet-4-20250514": "anthropic/claude-sonnet-4-20250514",
    # OpenAI
    "gpt-4o-mini": "openai/gpt-4o-mini",
    "gpt-4.1-mini": "openai/gpt-4.1-mini",
    "o4-mini": "openai/o4-mini",
    # Gemini
    "gemini-flash": "gemini/gemini-2.5-flash",
    "gemini-pro": "gemini/gemini-2.5-pro",
    # DeepSeek
    "deepseek-chat": "deepseek/deepseek-chat",
    "deepseek-reasoner": "deepseek/deepseek-reasoner",
    # OpenCode Zen
    "qwen3-coder": "opencode/qwen3-coder",
}


def normalize_model_name(model: str) -> str:
    """Resolve common aliases to provider/model format when possible."""
    model_name = model.strip()
    if not model_name:
        return model_name

    model_lower = model_name.lower()
    alias = _MODEL_ALIASES.get(model_lower)
    if alias:
        return alias

    if "/" in model_name:
        return model_name

    # Heuristic fallback for provider prefixes.
    if model_lower.startswith("claude-"):
        return f"anthropic/{model_name}"
    if model_lower.startswith(("gpt-", "o1", "o3", "o4")):
        return f"openai/{model_name}"
    if model_lower.startswith("gemini-"):
        return f"gemini/{model_name}"
    if model_lower.startswith("deepseek-"):
        return f"deepseek/{model_name}"
    if model_lower.startswith("opencode-"):
        return f"opencode/{model_name}"

    return model_name


def find_by_model(model: str) -> ProviderSpec | None:
    model_lower = normalize_model_name(model).lower()
    for spec in PROVIDERS:
        if spec.is_gateway:
            continue
        if any(kw in model_lower for kw in spec.keywords):
            return spec
    return None


def find_by_name(name: str) -> ProviderSpec | None:
    for spec in PROVIDERS:
        if spec.name == name:
            return spec
    return None
