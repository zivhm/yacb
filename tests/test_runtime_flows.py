import asyncio
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from core.agent.loop import AgentLoop
from core.agent.memory import MemoryStore
from core.bus.events import InboundMessage
from core.bus.queue import MessageBus
from core.config import AgentConfig, load_agent_settings, save_agent_settings
from core.cron.service import CronSchedule, CronService
from core.providers.base import LLMResponse
from core.tools.base import ToolRegistry
from core.tools.conversation_history import ConversationHistoryTool
from core.tools.cron import CronTool
from core.tools.memory import MemoryTool
from core.tools.shell import ExecTool
from core.utils.security import resolve_safe_path


class StubProvider:
    def __init__(self, responses: list[str]):
        self._responses = responses
        self.calls: list[dict[str, Any]] = []

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse:
        self.calls.append(
            {
                "messages": messages,
                "tools": tools,
                "model": model,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
        )
        content = self._responses.pop(0) if self._responses else "ok"
        return LLMResponse(content=content)

    def get_default_model(self) -> str:
        return "openai/gpt-4o-mini"


class StubHeavyRouter:
    async def route(self, message: str) -> tuple[str, str, str]:
        return "openai/gpt-4o-mini", message, "heavy"


class StubMediumRouter:
    async def route(self, message: str) -> tuple[str, str, str]:
        return "openai/gpt-4o-mini", message, "medium"


class StubGatewayRouter:
    async def route(self, message: str) -> tuple[str, str, str]:
        return "opencode/minimax-m2.5-free", message, "light"


class DummyTools:
    tool_names: set[str] = set()

    def get_definitions(self) -> list[dict[str, Any]]:
        return []

    def get(self, _name: str) -> None:
        return None


@pytest.mark.asyncio
async def test_inbound_to_outbound_flow(tmp_path: Path) -> None:
    bus = MessageBus()
    provider = StubProvider(["hello from yacb"])
    config = AgentConfig(model="openai/gpt-4o-mini", tools=[], max_iterations=3)
    agent = AgentLoop(bus=bus, provider=provider, agent_config=config, workspace=tmp_path)

    task = asyncio.create_task(agent.run())
    try:
        await bus.publish_inbound(
            InboundMessage(
                channel="telegram",
                sender_id="u1",
                chat_id="c1",
                content="hi there",
            )
        )
        outbound = await asyncio.wait_for(bus.consume_outbound(), timeout=5.0)
    finally:
        agent.stop()
        await asyncio.wait_for(task, timeout=3.0)

    assert outbound.channel == "telegram"
    assert outbound.chat_id == "c1"
    assert outbound.content == "hello from yacb"
    assert outbound.metadata.get("model") == "openai/gpt-4o-mini"
    assert len(provider.calls) == 1
    assert provider.calls[0]["messages"][-1]["content"] == "hi there"


@pytest.mark.asyncio
async def test_session_history_rehydrates_from_db_after_restart(tmp_path: Path) -> None:
    from core.storage.db import get_db

    cfg = AgentConfig(model="openai/gpt-4o-mini", tools=[], max_iterations=2)
    first_provider = StubProvider(["first reply"])
    first_agent = AgentLoop(
        bus=MessageBus(),
        provider=first_provider,
        agent_config=cfg,
        workspace=tmp_path,
    )
    await first_agent._process_message(
        InboundMessage(channel="telegram", sender_id="u1", chat_id="c1", content="first turn")
    )
    db = get_db(tmp_path)
    for _ in range(10):
        recent = await db.get_recent_messages("telegram", "c1", limit=2)
        if len(recent) >= 2:
            break
        await asyncio.sleep(0.1)

    second_provider = StubProvider(["second reply"])
    second_agent = AgentLoop(
        bus=MessageBus(),
        provider=second_provider,
        agent_config=cfg,
        workspace=tmp_path,
    )
    response = await second_agent._process_message(
        InboundMessage(channel="telegram", sender_id="u1", chat_id="c1", content="second turn")
    )

    assert response is not None
    sent_messages = second_provider.calls[0]["messages"]
    assert any(m.get("role") == "user" and m.get("content") == "first turn" for m in sent_messages)
    assert any(m.get("role") == "assistant" and m.get("content") == "first reply" for m in sent_messages)


@pytest.mark.asyncio
async def test_exchange_no_longer_writes_daily_conversations_notes(tmp_path: Path) -> None:
    bus = MessageBus()
    provider = StubProvider(["daily ack"])
    config = AgentConfig(model="openai/gpt-4o-mini", tools=[], max_iterations=2)
    agent = AgentLoop(bus=bus, provider=provider, agent_config=config, workspace=tmp_path)

    await agent._process_message(
        InboundMessage(
            channel="telegram",
            sender_id="u1",
            chat_id="daily",
            content="log this daily note entry",
        )
    )

    daily_dir = tmp_path / "memory" / "daily"
    daily_files = list(daily_dir.glob("*.md")) if daily_dir.exists() else []
    assert daily_files
    content = daily_files[0].read_text(encoding="utf-8")
    assert "## Conversations" not in content
    assert " Topic: " not in content
    assert " Note: New topic discussed: " not in content


def test_ensure_daily_note_sanitizes_legacy_conversations_section(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)
    today = datetime.now().strftime("%Y-%m-%d")
    daily_file = tmp_path / "memory" / "daily" / f"{today}.md"
    daily_file.parent.mkdir(parents=True, exist_ok=True)
    daily_file.write_text(
        (
            f"# {today} (Friday)\n\n"
            "## Notes\n\n"
            "## Conversations\n\n"
            "- 12:01 [telegram:1] Topic: old topic line\n"
            "- 12:02 [telegram:1] Note: New topic discussed: old note line\n\n"
            "## Learnings\n"
        ),
        encoding="utf-8",
    )

    store.ensure_daily_note()
    content = daily_file.read_text(encoding="utf-8")

    assert "## Conversations" not in content
    assert " Topic: " not in content
    assert " Note: New topic discussed: " not in content
    assert "## Notes" in content
    assert "## Learnings" in content


def test_ensure_daily_note_sanitizes_legacy_conversations_from_template(tmp_path: Path) -> None:
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    (memory_dir / "daily_template.md").write_text(
        "# {date} ({weekday})\n\n## Notes\n\n## Conversations\n\n## Learnings\n",
        encoding="utf-8",
    )
    store = MemoryStore(tmp_path)
    store.ensure_daily_note()

    today = datetime.now().strftime("%Y-%m-%d")
    daily_file = tmp_path / "memory" / "daily" / f"{today}.md"
    content = daily_file.read_text(encoding="utf-8")
    assert "## Conversations" not in content
    assert "## Notes" in content
    assert "## Learnings" in content


@pytest.mark.asyncio
async def test_gateway_models_skip_static_support_promotion(tmp_path: Path, monkeypatch) -> None:
    bus = MessageBus()
    provider = StubProvider(["hello from gateway model"])
    config = AgentConfig(model="opencode/kimi-k2.5-free", tools=["filesystem"], max_iterations=1)
    agent = AgentLoop(
        bus=bus,
        provider=provider,
        agent_config=config,
        workspace=tmp_path,
        tool_registry=DummyTools(),
        llm_router=StubGatewayRouter(),
    )

    # Simulate stale LiteLLM metadata returning False for this model.
    monkeypatch.setattr("core.agent.loop.supports_function_calling", lambda _m: False)

    response = await agent._process_message(
        InboundMessage(
            channel="telegram",
            sender_id="u1",
            chat_id="c1",
            content="hey",
        )
    )

    assert response is not None
    assert response.content == "hello from gateway model"
    assert provider.calls[0]["model"] == "opencode/minimax-m2.5-free"


@pytest.mark.asyncio
async def test_cron_delivery_flow(tmp_path: Path) -> None:
    delivered: list[str] = []
    delivered_event = asyncio.Event()

    async def on_job(job):
        delivered.append(job.payload.message)
        delivered_event.set()
        return None

    cron = CronService(workspace=tmp_path, on_job=on_job)
    await cron.start()
    try:
        schedule = CronSchedule(kind="at", at_ms=int(time.time() * 1000) + 150)
        job = cron.add_job(
            name="test reminder",
            schedule=schedule,
            message="ship it",
            deliver=True,
            channel="telegram",
            to="123",
            delete_after_run=True,
            direct_delivery=True,
        )
        await asyncio.wait_for(delivered_event.wait(), timeout=3.0)
        await asyncio.sleep(0.05)
    finally:
        cron.stop()

    assert delivered == ["ship it"]
    assert not any(j.id == job.id for j in cron.list_jobs())


@pytest.mark.asyncio
async def test_memory_recall_flow(tmp_path: Path) -> None:
    tool = MemoryTool(MemoryStore(tmp_path))

    remember = await tool.execute(
        action="remember",
        content="User likes Ethiopian coffee beans",
        category="preferences",
    )
    match = re.search(r"#(\d+)", remember)
    assert match is not None
    item_id = int(match.group(1))

    recall = await tool.execute(action="recall", content="Ethiopian")
    assert "[preferences]" in recall
    assert "Ethiopian coffee beans" in recall

    categories = await tool.execute(action="categories")
    assert "preferences" in categories

    forget = await tool.execute(action="forget", item_id=item_id)
    assert f"Removed item #{item_id}" == forget

    recall_after_forget = await tool.execute(action="recall", content="Ethiopian")
    assert "No memories matching: Ethiopian" == recall_after_forget


@pytest.mark.asyncio
async def test_conversation_history_recent_is_chat_scoped_by_default(tmp_path: Path) -> None:
    from core.storage.db import get_db

    db = get_db(tmp_path)
    await db.log_message("telegram", "c1", "u1", "user", "topic alpha")
    await db.log_message("telegram", "c1", "assistant", "assistant", "answer alpha")
    await db.log_message("telegram", "c2", "u2", "user", "topic beta")

    tool = ConversationHistoryTool(tmp_path)
    tool.set_context(channel="telegram", chat_id="c1")
    result = await tool.execute(action="recent", limit=10)

    assert "topic alpha" in result
    assert "answer alpha" in result
    assert "topic beta" not in result


@pytest.mark.asyncio
async def test_conversation_history_search_can_query_all_chats(tmp_path: Path) -> None:
    from core.storage.db import get_db

    db = get_db(tmp_path)
    await db.log_message("telegram", "c1", "u1", "user", "project hydra update")
    await db.log_message("discord", "c9", "u9", "user", "hydra issue found")

    tool = ConversationHistoryTool(tmp_path)
    result = await tool.execute(action="search", query="hydra", chat_only=False, limit=10)

    assert "telegram:c1" in result
    assert "discord:c9" in result


def test_resolve_safe_path_enforces_real_path_boundary(tmp_path: Path) -> None:
    allowed = tmp_path / "workspace"
    allowed.mkdir(parents=True, exist_ok=True)
    inside = resolve_safe_path(str(allowed / "notes" / "a.txt"), allowed)
    assert str(inside).startswith(str(allowed))

    with pytest.raises(PermissionError):
        resolve_safe_path(str(tmp_path / "workspace-other" / "a.txt"), allowed)


def test_parse_simple_relative_reminder_uses_after_time_context() -> None:
    parsed = AgentLoop._parse_simple_relative_reminder(
        "remind me in 5 minutes about the stars. i need to catch one"
    )
    assert parsed is not None
    in_seconds, message = parsed
    assert in_seconds == 300
    assert message == "the stars. i need to catch one"


def test_parse_simple_relative_reminder_handles_time_at_end() -> None:
    parsed = AgentLoop._parse_simple_relative_reminder("remind me to buy milk in 10 minutes")
    assert parsed is not None
    in_seconds, message = parsed
    assert in_seconds == 600
    assert message == "buy milk"


def test_parse_simple_relative_reminder_strips_punctuation_tail() -> None:
    parsed = AgentLoop._parse_simple_relative_reminder(
        "can you remind me to take my pills in like 3 minutes?"
    )
    assert parsed is not None
    in_seconds, message = parsed
    assert in_seconds == 180
    assert message == "take my pills"


@pytest.mark.asyncio
async def test_reset_snapshot_saves_important_info_and_skips_secrets(tmp_path: Path) -> None:
    bus = MessageBus()
    provider = StubProvider(["ok"])
    config = AgentConfig(model="openai/gpt-4o-mini", tools=[], max_iterations=1)
    agent = AgentLoop(bus=bus, provider=provider, agent_config=config, workspace=tmp_path)
    session_key = "telegram:123"

    agent._save_exchange(session_key, "my name is Ziv", "noted")
    agent._save_exchange(session_key, "for this skill always use ccxt for crypto", "got it")
    agent._save_exchange(session_key, "my api key is tvly-dev-2WDavV-NuCkA7UCyCpbB7iYcSDtbjaBfLH79", "ok")

    saved = await agent.snapshot_session_important_info(session_key)
    memory_text = (tmp_path / "memory" / "MEMORY.md").read_text(encoding="utf-8")

    assert saved == 2
    assert "my name is Ziv" in memory_text
    assert "always use ccxt for crypto" in memory_text
    assert "tvly-dev-2WDavV-NuCkA7UCyCpbB7iYcSDtbjaBfLH79" not in memory_text


@pytest.mark.asyncio
async def test_bang_prefix_executes_shell_without_llm(tmp_path: Path) -> None:
    bus = MessageBus()
    provider = StubProvider(["llm should not run"])
    config = AgentConfig(model="openai/gpt-4o-mini", tools=["shell"], max_iterations=2)
    tools = ToolRegistry()
    tools.register(ExecTool(timeout=5, working_dir=str(tmp_path), restrict_to_workspace=False))
    agent = AgentLoop(
        bus=bus,
        provider=provider,
        agent_config=config,
        workspace=tmp_path,
        tool_registry=tools,
    )

    response = await agent._process_message(
        InboundMessage(channel="telegram", sender_id="u1", chat_id="c1", content="!echo yacb")
    )

    assert response is not None
    assert response.metadata.get("model") == "system/shell"
    assert response.content.startswith("$ echo yacb")
    assert "yacb" in response.content.lower()
    assert len(provider.calls) == 0


@pytest.mark.asyncio
async def test_exec_tool_workspace_restriction_blocks_outside_paths(tmp_path: Path) -> None:
    tool = ExecTool(timeout=5, working_dir=str(tmp_path), restrict_to_workspace=True)

    ok = await tool.execute("echo ok")
    assert "ok" in ok.lower()

    blocked_abs = await tool.execute("cat /etc/hosts")
    assert blocked_abs.startswith("Error: Command blocked by workspace restriction")

    blocked_sub = await tool.execute("echo $(pwd)")
    assert blocked_sub.startswith("Error: Command blocked by workspace restriction")

    blocked_wd = await tool.execute("echo nope", working_dir=str(tmp_path.parent))
    assert blocked_wd == "Error: Working directory is outside workspace"


@pytest.mark.asyncio
async def test_cron_start_is_idempotent(tmp_path: Path) -> None:
    save_agent_settings(
        tmp_path,
        "cron_jobs",
        {
            "jobs": [
                {
                    "id": "job1",
                    "name": "once",
                    "enabled": True,
                    "schedule": {"kind": "every", "every_ms": 60000},
                    "payload": {"kind": "agent_turn", "message": "hello", "deliver": False},
                    "state": {},
                    "created_at_ms": 1,
                    "updated_at_ms": 1,
                    "delete_after_run": False,
                }
            ]
        },
    )

    cron = CronService(workspace=tmp_path)
    await cron.start()
    first_count = len(cron.list_jobs())
    await cron.start()
    second_count = len(cron.list_jobs())
    cron.stop()

    assert first_count == 1
    assert second_count == 1


@pytest.mark.asyncio
async def test_heavy_turn_keeps_turn_id_for_thinking_clear(tmp_path: Path) -> None:
    bus = MessageBus()
    provider = StubProvider(["done"])
    config = AgentConfig(model="openai/gpt-4o-mini", tools=[], max_iterations=2)
    agent = AgentLoop(
        bus=bus,
        provider=provider,
        agent_config=config,
        workspace=tmp_path,
        llm_router=StubHeavyRouter(),
    )

    response = await agent._process_message(
        InboundMessage(channel="telegram", sender_id="u1", chat_id="c1", content="think hard")
    )
    thinking = await asyncio.wait_for(bus.consume_outbound(), timeout=1.0)

    assert thinking.metadata.get("thinking") is True
    assert thinking.content == "working on it..."
    turn_id = thinking.metadata.get("turn_id")
    assert isinstance(turn_id, str) and turn_id
    assert response is not None
    assert response.metadata.get("clear_thinking") is True
    assert response.metadata.get("turn_id") == turn_id


@pytest.mark.asyncio
async def test_heavy_turn_appends_daily_note_line(tmp_path: Path) -> None:
    bus = MessageBus()
    provider = StubProvider(["done"])
    config = AgentConfig(model="openai/gpt-4o-mini", tools=[], max_iterations=2)
    agent = AgentLoop(
        bus=bus,
        provider=provider,
        agent_config=config,
        workspace=tmp_path,
        llm_router=StubHeavyRouter(),
    )

    await agent._process_message(
        InboundMessage(channel="telegram", sender_id="u1", chat_id="c1", content="think hard about the deploy plan")
    )

    today = datetime.now().strftime("%Y-%m-%d")
    daily_file = tmp_path / "memory" / "daily" / f"{today}.md"
    content = daily_file.read_text(encoding="utf-8")
    assert "Heavy update:" in content
    assert "[telegram:c1]" in content


@pytest.mark.asyncio
async def test_medium_turn_sends_working_placeholder_and_clears_it(tmp_path: Path) -> None:
    bus = MessageBus()
    provider = StubProvider(["done"])
    config = AgentConfig(model="openai/gpt-4o-mini", tools=[], max_iterations=2)
    agent = AgentLoop(
        bus=bus,
        provider=provider,
        agent_config=config,
        workspace=tmp_path,
        llm_router=StubMediumRouter(),
    )

    response = await agent._process_message(
        InboundMessage(channel="telegram", sender_id="u1", chat_id="c1", content="explain this")
    )
    placeholder = await asyncio.wait_for(bus.consume_outbound(), timeout=1.0)

    assert placeholder.metadata.get("thinking") is True
    assert placeholder.content == "working on it..."
    turn_id = placeholder.metadata.get("turn_id")
    assert isinstance(turn_id, str) and turn_id
    assert response is not None
    assert response.metadata.get("clear_thinking") is True
    assert response.metadata.get("turn_id") == turn_id


@pytest.mark.asyncio
async def test_periodic_daily_fill_uses_medium_model_when_significant(tmp_path: Path) -> None:
    from core.storage.db import get_db

    bus = MessageBus()
    provider = StubProvider(['{"significant": true, "note": "Model routing changed and restart workflow stabilized."}'])
    config = AgentConfig(model="openai/gpt-4o-mini", tools=[], max_iterations=2)
    agent = AgentLoop(bus=bus, provider=provider, agent_config=config, workspace=tmp_path)

    db = get_db(tmp_path)
    await db.log_message("telegram", "c1", "u1", "user", "switch medium model to openrouter sonnet 4")
    await db.log_message("telegram", "c1", "assistant", "assistant", "updated model settings")
    await db.log_message("telegram", "c1", "u1", "user", "restart and confirm")
    await db.log_message("telegram", "c1", "assistant", "assistant", "restart complete and verified")

    save_agent_settings(
        tmp_path,
        "daily_memory_fill",
        {
            "sessions": {
                "telegram:c1": {
                    "last_check_at": (datetime.now() - timedelta(hours=5)).isoformat(),
                    "last_fill_source_ts": (datetime.now() - timedelta(days=1)).isoformat(),
                }
            }
        },
    )

    await agent._maybe_run_periodic_daily_fill("telegram", "c1")

    today = datetime.now().strftime("%Y-%m-%d")
    daily_file = tmp_path / "memory" / "daily" / f"{today}.md"
    content = daily_file.read_text(encoding="utf-8")
    assert "Periodic update: Model routing changed and restart workflow stabilized" in content
    assert provider.calls
    assert provider.calls[0]["model"] == "openai/gpt-4o-mini"


@pytest.mark.asyncio
async def test_periodic_daily_fill_skips_before_four_hour_window(tmp_path: Path) -> None:
    bus = MessageBus()
    provider = StubProvider(['{"significant": true, "note": "should not run"}'])
    config = AgentConfig(model="openai/gpt-4o-mini", tools=[], max_iterations=2)
    agent = AgentLoop(bus=bus, provider=provider, agent_config=config, workspace=tmp_path)

    save_agent_settings(
        tmp_path,
        "daily_memory_fill",
        {
            "sessions": {
                "telegram:c1": {
                    "last_check_at": (datetime.now() - timedelta(hours=1)).isoformat(),
                    "last_fill_source_ts": (datetime.now() - timedelta(days=1)).isoformat(),
                }
            }
        },
    )

    await agent._maybe_run_periodic_daily_fill("telegram", "c1")

    assert provider.calls == []


@pytest.mark.asyncio
async def test_empty_final_response_triggers_text_finalization(tmp_path: Path) -> None:
    bus = MessageBus()
    provider = StubProvider(["", "finalized answer"])
    config = AgentConfig(model="openai/gpt-4o-mini", tools=[], max_iterations=2)
    agent = AgentLoop(bus=bus, provider=provider, agent_config=config, workspace=tmp_path)

    response = await agent._process_message(
        InboundMessage(channel="telegram", sender_id="u1", chat_id="c1", content="hello")
    )

    assert response is not None
    assert response.content == "finalized answer"
    assert len(provider.calls) == 2


@pytest.mark.asyncio
async def test_reminder_fallback_schedules_when_model_skips_cron(tmp_path: Path) -> None:
    bus = MessageBus()
    provider = StubProvider(["Sure, reminder set."])
    config = AgentConfig(model="openai/gpt-4o-mini", tools=["cron"], max_iterations=2)

    cron = CronService(workspace=tmp_path)
    await cron.start()
    try:
        tools = ToolRegistry()
        tools.register(CronTool(cron))
        agent = AgentLoop(
            bus=bus,
            provider=provider,
            agent_config=config,
            workspace=tmp_path,
            tool_registry=tools,
            cron_service=cron,
        )

        response = await agent._process_message(
            InboundMessage(
                channel="telegram",
                sender_id="u1",
                chat_id="123",
                content="remind me in 5 minutes to turn off the stove",
            )
        )
        jobs = cron.list_jobs()
    finally:
        cron.stop()

    assert response is not None
    assert "Reminder set for" in response.content
    assert len(jobs) == 1
    assert jobs[0].payload.channel == "telegram"
    assert jobs[0].payload.to == "123"
    assert "turn off the stove" in jobs[0].payload.message.lower()
    assert len(provider.calls) == 0


@pytest.mark.asyncio
async def test_reminder_never_claims_success_without_scheduled_job(tmp_path: Path) -> None:
    bus = MessageBus()
    provider = StubProvider(["Reminder set, done."])
    config = AgentConfig(model="openai/gpt-4o-mini", tools=["cron"], max_iterations=2)

    cron = CronService(workspace=tmp_path)
    await cron.start()
    try:
        tools = ToolRegistry()
        tools.register(CronTool(cron))
        agent = AgentLoop(
            bus=bus,
            provider=provider,
            agent_config=config,
            workspace=tmp_path,
            tool_registry=tools,
            cron_service=cron,
        )

        response = await agent._process_message(
            InboundMessage(
                channel="telegram",
                sender_id="u1",
                chat_id="123",
                content="remind me tomorrow morning to pay rent",
            )
        )
        jobs = cron.list_jobs()
    finally:
        cron.stop()

    assert response is not None
    assert "couldn't schedule" in response.content.lower()
    assert len(jobs) == 0
    assert len(provider.calls) == 1


@pytest.mark.asyncio
async def test_first_run_onboarding_is_deterministic_and_completes(tmp_path: Path) -> None:
    (tmp_path / "BOOTSTRAP.md").write_text("first-run onboarding", encoding="utf-8")

    bus = MessageBus()
    provider = StubProvider(["llm should not be used"])
    config = AgentConfig(model="openai/gpt-4o-mini", tools=[], max_iterations=2)
    agent = AgentLoop(bus=bus, provider=provider, agent_config=config, workspace=tmp_path)

    first = await agent._process_message(
        InboundMessage(channel="telegram", sender_id="u1", chat_id="c1", content="hey")
    )
    assert first is not None
    assert "Q1/7" in first.content
    assert first.metadata.get("model") == "system/onboarding"

    answers = [
        "Ziv",
        "Clawd",
        "very brief",
        "very direct",
        "one recommendation first",
        "moderate",
        "no emojis",
    ]
    final = None
    for answer in answers:
        final = await agent._process_message(
            InboundMessage(channel="telegram", sender_id="u1", chat_id="c1", content=answer)
        )
    assert final is not None
    assert "Onboarding complete" in final.content

    assert len(provider.calls) == 0
    assert not (tmp_path / "BOOTSTRAP.md").exists()
    identity = (tmp_path / "IDENTITY.md").read_text(encoding="utf-8")
    user = (tmp_path / "USER.md").read_text(encoding="utf-8")
    settings = load_agent_settings(tmp_path)
    assert "- Name: Clawd" in identity
    assert "- Name: Ziv" in user
    assert "- Things to avoid: no emojis" in user
    assert settings.get("bot_name") == "Clawd"


@pytest.mark.asyncio
async def test_onboarding_pause_allows_normal_chat_until_resume(tmp_path: Path) -> None:
    (tmp_path / "BOOTSTRAP.md").write_text("first-run onboarding", encoding="utf-8")

    bus = MessageBus()
    provider = StubProvider(["normal chat while paused"])
    config = AgentConfig(model="openai/gpt-4o-mini", tools=[], max_iterations=2)
    agent = AgentLoop(bus=bus, provider=provider, agent_config=config, workspace=tmp_path)

    await agent._process_message(
        InboundMessage(channel="telegram", sender_id="u1", chat_id="c1", content="hello")
    )
    paused = await agent._process_message(
        InboundMessage(channel="telegram", sender_id="u1", chat_id="c1", content="later")
    )
    assert paused is not None
    assert "paused onboarding" in paused.content.lower()

    normal = await agent._process_message(
        InboundMessage(channel="telegram", sender_id="u1", chat_id="c1", content="what can you do?")
    )
    assert normal is not None
    assert normal.content == "normal chat while paused"
    assert len(provider.calls) == 1

    resumed = await agent._process_message(
        InboundMessage(channel="telegram", sender_id="u1", chat_id="c1", content="resume onboarding")
    )
    assert resumed is not None
    assert "Resuming onboarding." in resumed.content
    assert "Q1/7" in resumed.content


@pytest.mark.asyncio
async def test_onboarding_state_is_scoped_per_chat(tmp_path: Path) -> None:
    (tmp_path / "BOOTSTRAP.md").write_text("first-run onboarding", encoding="utf-8")

    bus = MessageBus()
    provider = StubProvider(["unused"])
    config = AgentConfig(model="openai/gpt-4o-mini", tools=[], max_iterations=2)
    agent = AgentLoop(bus=bus, provider=provider, agent_config=config, workspace=tmp_path)

    first_chat = await agent._process_message(
        InboundMessage(channel="telegram", sender_id="u1", chat_id="chat-a", content="hello")
    )
    assert first_chat is not None
    assert "Q1/7" in first_chat.content

    q2_chat_a = await agent._process_message(
        InboundMessage(channel="telegram", sender_id="u1", chat_id="chat-a", content="Ziv")
    )
    assert q2_chat_a is not None
    assert "Q2/7" in q2_chat_a.content

    first_chat_b = await agent._process_message(
        InboundMessage(channel="telegram", sender_id="u2", chat_id="chat-b", content="hey there")
    )
    assert first_chat_b is not None
    assert "Q1/7" in first_chat_b.content
    assert len(provider.calls) == 0


@pytest.mark.asyncio
async def test_onboarding_status_command_does_not_advance_questions(tmp_path: Path) -> None:
    (tmp_path / "BOOTSTRAP.md").write_text("first-run onboarding", encoding="utf-8")

    bus = MessageBus()
    provider = StubProvider(["unused"])
    config = AgentConfig(model="openai/gpt-4o-mini", tools=[], max_iterations=2)
    agent = AgentLoop(bus=bus, provider=provider, agent_config=config, workspace=tmp_path)

    await agent._process_message(
        InboundMessage(channel="telegram", sender_id="u1", chat_id="c1", content="hello")
    )
    status = await agent._process_message(
        InboundMessage(channel="telegram", sender_id="u1", chat_id="c1", content="status onboarding")
    )
    assert status is not None
    assert "Onboarding status:" in status.content
    assert "Q1/7" in status.content

    still_q2 = await agent._process_message(
        InboundMessage(channel="telegram", sender_id="u1", chat_id="c1", content="Ziv")
    )
    assert still_q2 is not None
    assert "Q2/7" in still_q2.content
    assert len(provider.calls) == 0
