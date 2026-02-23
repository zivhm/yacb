"""Configuration schema and loader."""

import json
from pathlib import Path
from typing import Any

import yaml
from loguru import logger
from pydantic import BaseModel, Field, PrivateAttr


class TelegramConfig(BaseModel):
    enabled: bool = False
    token: str = ""
    allow_from: list[str] = Field(default_factory=list)
    proxy: str | None = None


class WhatsAppConfig(BaseModel):
    enabled: bool = False
    auth_dir: str = ""  # defaults to agent-workspace/<bot_name>/wa-auth/
    allow_from: list[str] = Field(default_factory=list)


class DiscordConfig(BaseModel):
    enabled: bool = False
    token: str = ""
    allow_from: list[str] = Field(default_factory=list)


class ChannelsConfig(BaseModel):
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)
    whatsapp: WhatsAppConfig = Field(default_factory=WhatsAppConfig)
    discord: DiscordConfig = Field(default_factory=DiscordConfig)


class ProviderConfig(BaseModel):
    api_key: str = ""
    api_base: str | None = None
    extra_headers: dict[str, str] | None = None


class ProvidersConfig(BaseModel):
    anthropic: ProviderConfig = Field(default_factory=ProviderConfig)
    openai: ProviderConfig = Field(default_factory=ProviderConfig)
    openrouter: ProviderConfig = Field(default_factory=ProviderConfig)
    opencode: ProviderConfig = Field(default_factory=ProviderConfig)
    deepseek: ProviderConfig = Field(default_factory=ProviderConfig)
    gemini: ProviderConfig = Field(default_factory=ProviderConfig)


class ExecToolConfig(BaseModel):
    timeout: int = 60


class SecurityAuditConfig(BaseModel):
    enabled: bool = False
    interval_minutes: int = Field(default=360, ge=5, le=10080)


class ToolsConfig(BaseModel):
    exec: ExecToolConfig = Field(default_factory=ExecToolConfig)
    restrict_to_workspace: bool = False
    tavily_api_key: str = ""
    security_audit: SecurityAuditConfig = Field(default_factory=SecurityAuditConfig)


class HeartbeatConfig(BaseModel):
    enabled: bool = False
    interval_minutes: int = 240
    deliver_to: str = ""                 # "channel:chat_id" e.g. "telegram:123456"
    active_hours_start: str = "08:00"    # HH:MM
    active_hours_end: str = "22:00"      # HH:MM
    suppress_empty: bool = True          # suppress HEARTBEAT_OK responses


class TierModelConfig(BaseModel):
    model: str = ""


class TierModelsConfig(BaseModel):
    light: TierModelConfig = Field(default_factory=TierModelConfig)
    medium: TierModelConfig = Field(default_factory=TierModelConfig)
    heavy: TierModelConfig = Field(default_factory=TierModelConfig)


class TierRulesConfig(BaseModel):
    short_message_max_chars: int = Field(default=80, ge=10, le=500)
    short_message_max_words: int = Field(default=12, ge=1, le=200)
    medium_keywords: list[str] = Field(
        default_factory=lambda: [
            "search",
            "read",
            "explain",
            "remind",
            "cron",
            "file",
            "tool",
        ]
    )
    heavy_keywords: list[str] = Field(
        default_factory=lambda: [
            "code",
            "debug",
            "refactor",
            "implement",
            "architecture",
            "optimize",
        ]
    )


class TierRouterConfig(BaseModel):
    enabled: bool = True
    tiers: TierModelsConfig = Field(default_factory=TierModelsConfig)
    rules: TierRulesConfig = Field(default_factory=TierRulesConfig)


class AgentConfig(BaseModel):
    """Configuration for a single agent."""
    model: str = "anthropic/claude-sonnet-4-20250514"
    system_prompt: str = "You are a helpful personal assistant."
    workspace: str = "agent-workspace/yacb"
    tools: list[str] = Field(default_factory=lambda: ["filesystem", "shell", "web", "message", "cron", "memory"])
    max_iterations: int = 20
    temperature: float = 0.7
    max_tokens: int = 8192
    bot_name: str = "yacb"
    interaction_style: str = "casual"  # casual, professional, brief, detailed
    chat_mode: str = "personal"  # personal, group
    tier_router: TierRouterConfig = Field(default_factory=TierRouterConfig)
    heartbeat: HeartbeatConfig = Field(default_factory=HeartbeatConfig)
    fallback_models: list[str] = Field(default_factory=list)
    fallback_max_attempts: int = Field(default=2, ge=1, le=5)


class Config(BaseModel):
    """Root configuration."""
    agents: dict[str, AgentConfig] = Field(default_factory=lambda: {"default": AgentConfig()})
    routes: dict[str, str] = Field(default_factory=dict)
    channels: ChannelsConfig = Field(default_factory=ChannelsConfig)
    providers: ProvidersConfig = Field(default_factory=ProvidersConfig)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)
    # Legacy: heartbeat at root level, migrated to per-agent on load
    heartbeat: HeartbeatConfig = Field(default_factory=HeartbeatConfig)
    _config_dir: Path = PrivateAttr(default_factory=lambda: Path.cwd())

    def get_agent_config(self, name: str) -> AgentConfig:
        return self.agents.get(name, self.agents.get("default", AgentConfig()))

    def resolve_agent(self, channel: str, chat_id: str) -> str:
        """Resolve which agent handles a given channel:chat_id."""
        key = f"{channel}:{chat_id}"
        return self.routes.get(key, "default")

    def get_provider(self, model: str | None = None) -> tuple[ProviderConfig | None, str | None]:
        """Find the right provider config for a model string."""
        from core.providers.registry import PROVIDERS, normalize_model_name
        model_name = model or "anthropic/claude-sonnet-4-20250514"
        model_lower = normalize_model_name(model_name).lower()

        for spec in PROVIDERS:
            p = getattr(self.providers, spec.name, None)
            if p and p.api_key and any(kw in model_lower for kw in spec.keywords):
                return p, spec.name

        # Fallback: first provider with a key
        for spec in PROVIDERS:
            p = getattr(self.providers, spec.name, None)
            if p and p.api_key:
                return p, spec.name
        return None, None

    def workspace_path(self, agent_name: str = "default") -> Path:
        agent = self.get_agent_config(agent_name)
        workspace = Path(agent.workspace).expanduser()
        if not workspace.is_absolute():
            workspace = self._config_dir / workspace
        return workspace.resolve()


def load_config(path: str | Path = "config.yaml") -> Config:
    """Load config from YAML file."""
    p = Path(path).expanduser()
    if p.exists():
        resolved_path = p.resolve()
        with open(resolved_path) as f:
            data = yaml.safe_load(f) or {}
        config = Config(**data)
        config._config_dir = resolved_path.parent
    else:
        resolved_path = p.resolve()
        config = Config()
        config._config_dir = resolved_path.parent

    # Migrate root-level heartbeat into agent configs that don't have one set
    if config.heartbeat.enabled:
        for agent_config in config.agents.values():
            if not agent_config.heartbeat.enabled:
                agent_config.heartbeat = config.heartbeat.model_copy()

    return config


_SETTINGS_FILE = "settings.json"

# Fields from AgentConfig that belong in settings.json (behavior, not infrastructure)
_SETTINGS_FIELDS = {
    "model", "system_prompt", "bot_name", "interaction_style", "chat_mode",
    "temperature", "max_tokens", "max_iterations", "tier_router", "heartbeat",
}


def _settings_path(workspace: Path) -> Path:
    return workspace / _SETTINGS_FILE


def load_agent_settings(workspace: Path) -> dict:
    """Load settings.json from workspace. Returns empty dict if not found."""
    p = _settings_path(workspace)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"Failed to load {p}: {e}")
    return {}


def save_agent_settings(workspace: Path, key: str, value: Any) -> None:
    """Read-modify-write a single section of settings.json."""
    p = _settings_path(workspace)
    p.parent.mkdir(parents=True, exist_ok=True)
    data = load_agent_settings(workspace)
    data[key] = value
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def apply_settings_overlay(agent_config: AgentConfig, settings: dict) -> None:
    """Apply settings.json fields onto an AgentConfig (mutates in place)."""
    for key in _SETTINGS_FIELDS:
        if key not in settings:
            continue
        val = settings[key]
        if key == "tier_router" and isinstance(val, dict):
            agent_config.tier_router = TierRouterConfig(**val)
        elif key == "heartbeat" and isinstance(val, dict):
            agent_config.heartbeat = HeartbeatConfig(**val)
        else:
            setattr(agent_config, key, val)


def migrate_legacy_json(workspace: Path) -> None:
    """Migrate old verbose_logs.json and cron_jobs.json into settings.json."""
    settings = load_agent_settings(workspace)
    changed = False

    # Migrate verbose_logs.json
    old_verbose = workspace / "verbose_logs.json"
    if old_verbose.exists() and "verbose_logs" not in settings:
        try:
            data = json.loads(old_verbose.read_text())
            settings["verbose_logs"] = data
            changed = True
            logger.info(f"Migrated {old_verbose} into settings.json")
        except Exception:
            pass

    # Migrate cron_jobs.json
    old_cron = workspace / "cron_jobs.json"
    if old_cron.exists() and "cron_jobs" not in settings:
        try:
            data = json.loads(old_cron.read_text())
            settings["cron_jobs"] = data
            changed = True
            logger.info(f"Migrated {old_cron} into settings.json")
        except Exception:
            pass

    if changed:
        p = _settings_path(workspace)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(settings, indent=2, ensure_ascii=False), encoding="utf-8")


def seed_settings_from_config(workspace: Path, agent_config: AgentConfig) -> None:
    """Seed settings.json from AgentConfig if it doesn't exist yet (first-time migration)."""
    p = _settings_path(workspace)
    if p.exists():
        return
    settings: dict[str, Any] = {}
    for key in _SETTINGS_FIELDS:
        val = getattr(agent_config, key)
        if val is None:
            continue
        if hasattr(val, "model_dump"):
            settings[key] = val.model_dump()
        else:
            settings[key] = val
    if settings:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(settings, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info(f"Seeded {p} from agent config")
