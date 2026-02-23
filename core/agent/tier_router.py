"""Deterministic tier router for selecting chat models."""

from __future__ import annotations

from core.config import TierRouterConfig

_VALID_TIERS = {"light", "medium", "heavy"}


class TierRouter:
    """Routes messages to light/medium/heavy tiers using deterministic rules."""

    def __init__(self, config: TierRouterConfig, default_model: str) -> None:
        self.config = config
        self.default_model = default_model

    def route(self, message: str) -> tuple[str, str, str]:
        """Return (tier, cleaned_message, selected_model)."""
        forced = self._parse_tier_override(message)
        if forced:
            tier, cleaned = forced
            return tier, cleaned, self._resolve_model(tier)

        tier = self._classify(message)
        return tier, message, self._resolve_model(tier)

    def _classify(self, message: str) -> str:
        text = (message or "").strip().lower()
        if not text:
            return "medium"

        rules = self.config.rules
        if any(keyword in text for keyword in rules.heavy_keywords):
            return "heavy"
        if any(keyword in text for keyword in rules.medium_keywords):
            return "medium"

        words = text.split()
        if len(text) <= rules.short_message_max_chars and len(words) <= rules.short_message_max_words:
            return "light"
        return "medium"

    def _resolve_model(self, tier: str) -> str:
        if not self.config.enabled:
            return self.default_model

        tier_cfg = getattr(self.config.tiers, tier)
        configured = (tier_cfg.model or "").strip()
        if configured:
            return configured

        if tier == "medium":
            return self.default_model

        medium = (self.config.tiers.medium.model or "").strip()
        return medium or self.default_model

    def model_for_tier(self, tier: str) -> str:
        """Return the model configured for a tier."""
        return self._resolve_model(tier)

    def _parse_tier_override(self, message: str) -> tuple[str, str] | None:
        raw = (message or "").strip()
        if not raw.lower().startswith("!tier"):
            return None

        parts = raw.split(None, 2)
        if len(parts) < 3:
            raise ValueError("Usage: !tier <light|medium|heavy> <message>")

        tier = parts[1].strip().lower()
        if tier not in _VALID_TIERS:
            raise ValueError("Usage: !tier <light|medium|heavy> <message>")

        content = parts[2].strip()
        if not content:
            raise ValueError("Usage: !tier <light|medium|heavy> <message>")
        return tier, content

    def get_status(self) -> str:
        return "\n".join(
            [
                "Tier router:",
                f"  enabled: {self.config.enabled}",
                f"  light : {self._resolve_model('light')}",
                f"  medium: {self._resolve_model('medium')}",
                f"  heavy : {self._resolve_model('heavy')}",
            ]
        )

    def update_default_model(self, model: str) -> None:
        self.default_model = model
