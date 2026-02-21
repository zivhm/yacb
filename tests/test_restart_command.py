from pathlib import Path

import pytest

from core.agent.loop import AgentLoop
from core.bus.events import InboundMessage
from core.bus.queue import MessageBus
from core.config import AgentConfig
from core.providers.base import LLMResponse


class StubProvider:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def chat(self, *args, **kwargs) -> LLMResponse:  # pragma: no cover - should not run
        self.calls.append({"args": args, "kwargs": kwargs})
        return LLMResponse(content="unexpected")

    def get_default_model(self) -> str:
        return "openai/gpt-4o-mini"


@pytest.mark.asyncio
async def test_restart_command_requires_confirmation(tmp_path: Path) -> None:
    bus = MessageBus()
    provider = StubProvider()
    config = AgentConfig(model="openai/gpt-4o-mini", tools=[], max_iterations=1)
    agent = AgentLoop(bus=bus, provider=provider, agent_config=config, workspace=tmp_path)

    response = await agent._process_message(
        InboundMessage(channel="telegram", sender_id="u1", chat_id="c1", content="!restart")
    )

    assert response is not None
    assert "warning placeholder" in response.content
    assert "Send `!restart now` to restart the yacb service." in response.content
    assert response.metadata.get("restart_requested") is None
    assert provider.calls == []


@pytest.mark.asyncio
async def test_restart_command_sets_restart_flag_on_confirmation(tmp_path: Path) -> None:
    bus = MessageBus()
    provider = StubProvider()
    config = AgentConfig(model="openai/gpt-4o-mini", tools=[], max_iterations=1)
    agent = AgentLoop(bus=bus, provider=provider, agent_config=config, workspace=tmp_path)

    response = await agent._process_message(
        InboundMessage(channel="telegram", sender_id="u1", chat_id="c1", content="!restart now")
    )

    assert response is not None
    assert response.content == "Restarting yacb now..."
    assert response.metadata.get("restart_requested") is True
    assert provider.calls == []


@pytest.mark.asyncio
async def test_update_command_requires_confirmation(tmp_path: Path) -> None:
    bus = MessageBus()
    provider = StubProvider()
    config = AgentConfig(model="openai/gpt-4o-mini", tools=[], max_iterations=1)
    agent = AgentLoop(bus=bus, provider=provider, agent_config=config, workspace=tmp_path)

    response = await agent._process_message(
        InboundMessage(channel="telegram", sender_id="u1", chat_id="c1", content="!update")
    )

    assert response is not None
    assert "Send `!update now`" in response.content
    assert response.metadata.get("update_requested") is None
    assert provider.calls == []


@pytest.mark.asyncio
async def test_update_command_sets_update_flag_on_confirmation(tmp_path: Path) -> None:
    bus = MessageBus()
    provider = StubProvider()
    config = AgentConfig(model="openai/gpt-4o-mini", tools=[], max_iterations=1)
    agent = AgentLoop(bus=bus, provider=provider, agent_config=config, workspace=tmp_path)

    response = await agent._process_message(
        InboundMessage(channel="telegram", sender_id="u1", chat_id="c1", content="!update now")
    )

    assert response is not None
    assert "Updating yacb now" in response.content
    assert response.metadata.get("update_requested") is True
    assert provider.calls == []
