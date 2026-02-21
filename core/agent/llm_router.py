"""LLM Router: classifies messages to pick the cheapest capable model."""

from __future__ import annotations

from loguru import logger

from core.config import LLMRouterConfig
from core.providers.base import LLMProvider

# Per-provider search patterns: try each in order, first match wins.
# Patterns are matched against litellm's model list for that provider.
# TODO: replace hard-coded tier patterns with a dedicated tier classifier
# for model capabilities/cost (provider-aware, dynamic, and test-backed).
_TIER_PATTERNS: dict[str, dict[str, list[str]]] = {
    "anthropic": {
        "light": ["haiku-4.5", "haiku4.5", "claude-haiku-4.5"],
        "heavy": ["sonnet-4.6", "sonnet4.6", "claude-sonnet-4.6", "sonnet-4.5", "sonnet4.5", "claude-sonnet-4.5", "opus-4.6", "opus4.6", "claude-opus-4.6"],
    },
    "openai": {
        "light": ["gpt-5-nano", "gpt-5-mini", "gpt-4o-mini"],
        "heavy": ["gpt-5.3-codex", "gpt-5.2-codex", "gpt-5.3"],
    },
    "gemini": {
        "light": ["gemini-2.5-flash-lite", "gemini-2.5-flash", "gemini-2.0-flash", "gemini-flash"],
        "heavy": ["gemini-2.5-pro", "gemini-pro"],
    },
    "deepseek": {
        "light": ["deepseek-chat", "deepseek-v3"],
        "heavy": ["deepseek-reasoner", "deepseek-r1"],
    },
    "openrouter": {
        "light": ["haiku-4.5", "haiku4.5", "claude-haiku-4.5"],
        "heavy": ["sonnet-4.6", "sonnet4.6", "claude-sonnet-4.6", "sonnet-4.5", "sonnet4.5", "claude-sonnet-4.5", "opus-4.6", "opus4.6", "claude-opus-4.6"],
    },
    "opencode": {
        "light": ["kimi", "minimax", "glm", "qwen3-30b", "qwen3"],
        "heavy": ["qwen3-coder", "minimax-m2.5", "kimi-k2.5", "glm-4.7"],
    },
}

# Provider keywords for detection from model strings
_PROVIDER_KEYWORDS = ("openrouter", "opencode", "anthropic", "openai", "gemini", "deepseek")

_CLASSIFIER_SYSTEM = (
    "You are a message classifier. You MUST respond with exactly one word: light, medium, or heavy.\n\n"
    "light = simple questions, greetings, skill use, dates, definitions, yes/no (no tools needed)\n"
    "medium = conversation, explanations, file tasks, web searches, anything requiring tools\n"
    "heavy = coding, complex reasoning, debugging, multi-step analysis, creative writing"
)

_CLASSIFIER_FEW_SHOT = [
    {"role": "system", "content": _CLASSIFIER_SYSTEM},
    {"role": "user", "content": "hey there",},
    {"role": "assistant", "content": "light"},
    {"role": "user", "content": "can you search online for...?"},
    {"role": "assistant", "content": "medium"},
    {"role": "user", "content": "write me a recursive fibonacci in rust"},
    {"role": "assistant", "content": "heavy"},
]

_PREFIX_MAP: dict[str, str] = {
    "!light": "light",
    "!heavy": "heavy",
    "!think": "heavy",
}

_LIGHT_HINTS = {
    "hi", "hello", "hey", "yo", "sup", "thanks", "thank you", "thx", "tnx", "ok", "okay",
}
_MEDIUM_HINTS = (
    "remind", "reminder", "schedule", "cron",
    "search", "look up", "find", "read", "summarize", "weather", "news",
    "help", "explain", "what can you",
)
_HEAVY_HINTS = (
    "code", "coding", "debug", "bug", "refactor", "implement", "algorithm",
    "architecture", "optimize", "performance", "multi-step", "analyze",
)

_EXCLUDE_KEYWORDS = (
    "image", "audio", "tts", "realtime", "vision", "embed",
    "moderation", "dall", "whisper", "sora", "veo", "imagen",
    "live-", "transcribe", "search", "preview-image",
    "learnlm", "gemma", "codex", "instruct", "ft:",
    "fast/", "us/",
)

def _resolve_tier_model(provider: str, tier: str, prefix: str = "") -> str | None:
    """Query litellm's model list to find the best model for a tier.

    Returns a full model string like 'anthropic/claude-3-5-haiku-20241022'
    or None if nothing matched.
    """
    try:
        import litellm
        all_models: list[str] = litellm.models_by_provider.get(provider, [])
    except Exception:
        return None

    if not all_models:
        return None

    # Pre-filter: only chat-capable models
    chat_models = [
        m for m in all_models
        if not any(x in m.lower() for x in _EXCLUDE_KEYWORDS)
    ]

    patterns = _TIER_PATTERNS.get(provider, {}).get(tier, [])

    for pattern in patterns:
        matches = [m for m in chat_models if pattern in m.lower()]
        if not matches:
            continue

        # Prefer dated versions (contain a date like 2024/2025/2026) over -latest
        dated = [m for m in matches if any(f"20{y}" in m for y in range(24, 30))]
        pool = dated if dated else matches

        # Pick the latest dated version
        best = sorted(pool)[-1]

        if prefix:
            return f"{prefix}/{best}"
        if not best.startswith(f"{provider}/"):
            return f"{provider}/{best}"
        return best

    return None


def _auto_resolve_defaults(provider_key: str) -> dict[str, str]:
    """Auto-resolve light/heavy models for a provider from litellm."""
    results: dict[str, str] = {}

    # OpenRouter uses anthropic models underneath
    lookup_provider = "anthropic" if provider_key == "openrouter" else provider_key
    prefix = "openrouter" if provider_key == "openrouter" else ""

    for tier in ("light", "heavy"):
        model = _resolve_tier_model(lookup_provider, tier, prefix)
        if model:
            results[tier] = model

    return results


class LLMRouter:
    """Picks the cheapest model that can handle a given message."""

    def __init__(
        self,
        provider: LLMProvider,
        config: LLMRouterConfig,
        default_model: str,
    ) -> None:
        self.provider = provider
        self.config = config
        self.default_model = default_model

        # Resolve tier models
        provider_key = self._detect_provider(default_model)
        defaults = _auto_resolve_defaults(provider_key)

        self.light_model = config.light_model or defaults.get("light", default_model)
        self.heavy_model = config.heavy_model or defaults.get("heavy", default_model)
        self.classifier_model = config.classifier_model or self.light_model

        # Only log auto-resolved defaults when they were actually used
        if defaults:
            used = {}
            if not config.light_model and "light" in defaults:
                used["light"] = defaults["light"]
            if not config.heavy_model and "heavy" in defaults:
                used["heavy"] = defaults["heavy"]
            if used:
                logger.info(f"LLM Router: auto-resolved for '{provider_key}': {used}")

        logger.info(
            f"LLM Router initialized: light={self.light_model}, "
            f"medium={self.default_model}, heavy={self.heavy_model}, "
            f"classifier={self.classifier_model}"
        )

    async def route(self, message: str) -> tuple[str, str, str]:
        """Route a message to the appropriate model.

        Returns (model, cleaned_message, tier).
        """
        # Check for prefix overrides first
        tier, cleaned = self._check_prefix(message)

        if tier is not None:
            model = self._resolve_model(tier)
            logger.info(f"LLM Router: prefix override '{tier}' -> {model}")
            return model, cleaned, tier

        # No prefix — ask the classifier
        tier = await self._classify(message)
        model = self._resolve_model(tier)
        logger.info(f"LLM Router: classified '{tier}' -> {model}")
        return model, cleaned, tier

    def _check_prefix(self, message: str) -> tuple[str | None, str]:
        """Check for prefix overrides like !light, !heavy, !think.

        Returns (tier_or_None, stripped_message).
        """
        stripped = message.lstrip()
        for prefix, tier in _PREFIX_MAP.items():
            if stripped.lower().startswith(prefix):
                rest = stripped[len(prefix):].lstrip()
                return tier, rest
        return None, message

    async def _classify(self, message: str) -> str:
        """Use the cheapest model to classify the message into a tier."""
        messages = _CLASSIFIER_FEW_SHOT + [{"role": "user", "content": message[:500]}]

        try:
            response = await self.provider.chat(
                messages=messages,
                model=self.classifier_model,
                max_tokens=16,
                temperature=0.1,
            )
            raw = (response.content or "").strip().lower()
            logger.debug(f"LLM Router: classifier raw response: '{raw}'")
            if raw in ("light", "medium", "heavy"):
                return raw
            # Fuzzy match: take the first recognized word
            for word in raw.split():
                if word in ("light", "medium", "heavy"):
                    logger.debug(f"LLM Router: fuzzy matched '{word}' from '{raw}'")
                    return word
            if not raw:
                guessed = self._heuristic_tier(message)
                logger.info(f"LLM Router: classifier returned empty, heuristic -> {guessed}")
                return guessed
            guessed = self._heuristic_tier(message)
            logger.warning(f"LLM Router: classifier returned '{raw}', heuristic -> {guessed}")
            return guessed
        except Exception as e:
            guessed = self._heuristic_tier(message)
            logger.warning(f"LLM Router: classifier failed ({e}), heuristic -> {guessed}")
            return guessed

    @staticmethod
    def _heuristic_tier(message: str) -> str:
        """Deterministic fallback when classifier output is unusable."""
        text = message.strip().lower()
        if not text:
            return "medium"

        if any(hint in text for hint in _HEAVY_HINTS):
            return "heavy"
        if any(hint in text for hint in _MEDIUM_HINTS):
            return "medium"

        if text in _LIGHT_HINTS:
            return "light"

        words = text.split()
        if len(words) <= 3 and all(len(w) <= 6 for w in words):
            return "light"
        return "medium"

    def _resolve_model(self, tier: str) -> str:
        """Map a tier to a concrete model string."""
        if tier == "light":
            return self.light_model
        if tier == "heavy":
            return self.heavy_model
        return self.default_model

    def update_default_model(self, model: str) -> None:
        """Update the default (medium) model and re-resolve light/heavy tiers."""
        self.default_model = model
        provider_key = self._detect_provider(model)
        defaults = _auto_resolve_defaults(provider_key)
        # Only re-resolve tiers that weren't explicitly configured
        if not self.config.light_model:
            self.light_model = defaults.get("light", model)
        if not self.config.heavy_model:
            self.heavy_model = defaults.get("heavy", model)
        self.classifier_model = self.config.classifier_model or self.light_model
        logger.info(
            f"LLM Router updated: light={self.light_model}, "
            f"medium={self.default_model}, heavy={self.heavy_model}"
        )

    def update_tier_model(self, tier: str, model: str) -> None:
        """Update a specific tier's model."""
        if tier == "light":
            self.light_model = model
            self.config.light_model = model
            # Classifier follows light unless explicitly set
            if not self.config.classifier_model:
                self.classifier_model = model
        elif tier == "heavy":
            self.heavy_model = model
            self.config.heavy_model = model
        elif tier == "medium":
            self.update_default_model(model)
            return
        logger.info(f"LLM Router: {tier} tier updated to {model}")

    def get_status(self) -> str:
        """Return a human-readable status of the current model configuration."""
        lines = [
            "Current model configuration:",
            f"  light  : {self.light_model}",
            f"  medium : {self.default_model}",
            f"  heavy  : {self.heavy_model}",
            f"  classifier: {self.classifier_model}",
        ]
        return "\n".join(lines)

    @staticmethod
    def _detect_provider(model: str) -> str:
        """Detect provider from a model string like 'anthropic/claude-...'."""
        model_lower = model.lower()
        for key in _PROVIDER_KEYWORDS:
            if key in model_lower:
                return key
        return ""
