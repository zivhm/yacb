"""Multi-agent router: maps channel:chat_id to agent configurations."""

from pathlib import Path
from typing import Any

from loguru import logger

from core.agent.loop import AgentLoop
from core.bus.queue import MessageBus
from core.config import (
    AgentConfig,
    Config,
    apply_settings_overlay,
    load_agent_settings,
    migrate_legacy_json,
    seed_settings_from_config,
)
from core.providers.litellm_provider import LiteLLMProvider
from core.tools.base import ToolRegistry


class AgentRouter:
    """Routes messages to the appropriate agent based on channel:chat_id."""

    def __init__(self, config: Config, bus: MessageBus):
        self.config = config
        self.bus = bus
        self._agents: dict[str, AgentLoop] = {}
        self._providers: dict[str, LiteLLMProvider] = {}

    def resolve(self, channel: str, chat_id: str) -> str:
        """Resolve which agent name handles this channel:chat_id."""
        return self.config.resolve_agent(channel, chat_id)

    def get_or_create_agent(self, agent_name: str) -> AgentLoop:
        """Get existing or create new agent loop for the given agent name."""
        if agent_name in self._agents:
            return self._agents[agent_name]

        agent_config = self.config.get_agent_config(agent_name)
        workspace = self.config.workspace_path(agent_name)
        workspace.mkdir(parents=True, exist_ok=True)

        # Settings migration: seed from config, migrate old JSON files, apply overlay
        seed_settings_from_config(workspace, agent_config)
        migrate_legacy_json(workspace)
        settings = load_agent_settings(workspace)
        apply_settings_overlay(agent_config, settings)

        # Get or create provider
        provider = self._get_provider(agent_config)

        # Build cron service ONCE - shared between AgentLoop and CronTool
        cron_service = self._build_cron(agent_name, workspace)

        # Build tool registry (pass the same cron_service)
        tools = self._build_tools(agent_config, workspace, cron_service)

        from core.agent.tier_router import TierRouter
        tier_router = TierRouter(agent_config.tier_router, agent_config.model)

        agent = AgentLoop(
            bus=self.bus,
            provider=provider,
            agent_config=agent_config,
            workspace=workspace,
            tool_registry=tools,
            cron_service=cron_service,
            tier_router=tier_router,
            agent_name=agent_name,
        )

        self._agents[agent_name] = agent
        logger.info(f"Created agent '{agent_name}' (model={agent_config.model}, workspace={workspace})")
        return agent

    def _get_provider(self, agent_config: AgentConfig) -> LiteLLMProvider:
        """Get or create LLM provider for agent config."""
        provider_cfg, provider_name = self.config.get_provider(agent_config.model)
        from core.providers.registry import PROVIDERS
        provider_spec = next((spec for spec in PROVIDERS if spec.name == provider_name), None)
        resolved_api_base = provider_cfg.api_base if provider_cfg else None
        if not resolved_api_base and provider_spec and provider_spec.default_api_base:
            resolved_api_base = provider_spec.default_api_base
        provider_api_keys = {
            spec.name: p.api_key
            for spec in PROVIDERS
            if (p := getattr(self.config.providers, spec.name, None)) and p.api_key
        }
        fallback_key = ",".join(agent_config.fallback_models)
        cache_key = (
            f"{provider_name}:{agent_config.model}:"
            f"{resolved_api_base}:{agent_config.fallback_max_attempts}:{fallback_key}"
        )

        if cache_key not in self._providers:
            self._providers[cache_key] = LiteLLMProvider(
                api_key=provider_cfg.api_key if provider_cfg else None,
                api_base=resolved_api_base,
                default_model=agent_config.model,
                extra_headers=provider_cfg.extra_headers if provider_cfg else None,
                provider_name=provider_name,
                fallback_models=agent_config.fallback_models,
                fallback_max_attempts=agent_config.fallback_max_attempts,
                provider_api_keys=provider_api_keys,
            )
        return self._providers[cache_key]

    def _build_tools(self, agent_config: AgentConfig, workspace: Path, cron_service: Any = None) -> ToolRegistry:
        """Build tool registry based on agent config."""
        from core.tools.filesystem import EditFileTool, ListDirTool, ReadFileTool, WriteFileTool
        from core.tools.message import MessageTool
        from core.tools.shell import ExecTool
        from core.tools.web import WebFetchTool, WebSearchTool

        allowed_tools = set(agent_config.tools)
        restrict = self.config.tools.restrict_to_workspace
        allowed_dir = workspace if restrict else None

        tools = ToolRegistry()

        if "filesystem" in allowed_tools:
            tools.register(ReadFileTool(allowed_dir=allowed_dir))
            tools.register(WriteFileTool(allowed_dir=allowed_dir))
            tools.register(EditFileTool(allowed_dir=allowed_dir))
            tools.register(ListDirTool(allowed_dir=allowed_dir))

        if "shell" in allowed_tools:
            tools.register(ExecTool(
                timeout=self.config.tools.exec.timeout,
                working_dir=str(workspace),
                restrict_to_workspace=restrict,
            ))

        if "web" in allowed_tools:
            tools.register(WebSearchTool(api_key=self.config.tools.tavily_api_key))
            tools.register(WebFetchTool())

        if "message" in allowed_tools:
            tools.register(MessageTool(send_callback=self.bus.publish_outbound))

        if "cron" in allowed_tools and cron_service:
            from core.tools.cron import CronTool
            tools.register(CronTool(cron_service))

        if "memory" in allowed_tools:
            from core.agent.memory import MemoryStore
            from core.tools.memory import MemoryTool
            memory_store = MemoryStore(workspace)
            tools.register(MemoryTool(memory_store))

        from core.tools.conversation_history import ConversationHistoryTool
        tools.register(ConversationHistoryTool(workspace))

        from core.tools.token_usage import TokenUsageTool
        tools.register(TokenUsageTool(workspace))

        return tools

    def _build_cron(self, agent_name: str, workspace: Path) -> Any:
        """Build cron service for an agent."""
        from core.cron.service import CronService
        return CronService(workspace=workspace)

    def get_agent_names(self) -> list[str]:
        return list(self._agents.keys())
