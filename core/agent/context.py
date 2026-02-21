"""Context builder for assembling agent prompts."""

import platform
from datetime import datetime
from pathlib import Path
from typing import Any

from core.config import AgentConfig
from core.prompts.loader import read_bootstrap, read_text

_MAX_HISTORY_MESSAGES_IN_PROMPT = 40
_MAX_BOOTSTRAP_CONTEXT_CHARS = 5000
_MAX_ACTIVE_SKILLS_CONTEXT_CHARS = 3000
_MAX_SKILLS_SUMMARY_CHARS = 3500


def _clip_context(text: str, max_chars: int, label: str) -> str:
    if len(text) <= max_chars:
        return text
    marker = f"\n\n...[{label} truncated for prompt efficiency]...\n\n"
    keep = max_chars - len(marker)
    if keep <= 40:
        return text[:max_chars]
    head = keep // 2
    tail = keep - head
    return text[:head] + marker + text[-tail:]


class ContextBuilder:
    """Builds system prompt + messages for the agent."""

    def __init__(self, workspace: Path, system_prompt: str = "", agent_config: AgentConfig | None = None):
        self.workspace = workspace
        self.custom_system_prompt = system_prompt
        self.agent_config = agent_config or AgentConfig()
        self._memory = None
        self._skills = None

    @property
    def memory(self):
        if self._memory is None:
            from core.agent.memory import MemoryStore
            self._memory = MemoryStore(self.workspace)
        return self._memory

    @property
    def skills(self):
        if self._skills is None:
            from core.agent.skills import SkillsLoader
            self._skills = SkillsLoader(self.workspace)
        return self._skills

    def _read_workspace_file(self, name: str) -> str:
        path = self.workspace / name
        if not path.exists():
            return ""
        try:
            return path.read_text(encoding="utf-8").strip()
        except Exception:
            return ""

    def _ensure_bootstrap_files(self) -> None:
        for name in ["IDENTITY.md", "SOUL.md", "USER.md", "TOOLS.md", "AGENTS.md"]:
            path = self.workspace / name
            if path.exists():
                continue
            content = read_bootstrap(name)
            if not content:
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")

    def _get_bootstrap_context(self) -> str:
        self._ensure_bootstrap_files()
        sections = []
        bootstrap = self._read_workspace_file("BOOTSTRAP.md")
        if bootstrap:
            sections.append(f"### BOOTSTRAP.md\n\n{bootstrap}")
        for name in ["IDENTITY.md", "SOUL.md", "USER.md", "TOOLS.md", "AGENTS.md"]:
            content = self._read_workspace_file(name)
            if content:
                sections.append(f"### {name}\n\n{content}")
        return "\n\n---\n\n".join(sections)

    async def build_system_prompt_async(self) -> str:
        """Build system prompt with full 3-layer memory (async)."""
        self.memory.ensure_daily_note()

        parts = []
        parts.append(self._get_identity())

        bootstrap = self._get_bootstrap_context()
        if bootstrap:
            parts.append(
                "# Workspace Files\n\n"
                + _clip_context(bootstrap, _MAX_BOOTSTRAP_CONTEXT_CHARS, "workspace files")
            )

        memory_ctx = await self.memory.get_full_memory_context()
        if memory_ctx:
            parts.append(f"# Memory\n\n{memory_ctx}")

        always_skills = self.skills.get_always_skills()
        if always_skills:
            content = self.skills.load_skills_for_context(always_skills)
            if content:
                parts.append(
                    "# Active Skills\n\n"
                    + _clip_context(content, _MAX_ACTIVE_SKILLS_CONTEXT_CHARS, "active skills")
                )

        summary = self.skills.build_skills_summary()
        if summary:
            parts.append(
                "# Skills\n\n"
                "The following skills extend your capabilities. "
                "To use a skill, read its SKILL.md file using the read_file tool.\n\n"
                + _clip_context(summary, _MAX_SKILLS_SUMMARY_CHARS, "skills index")
            )

        return "\n\n---\n\n".join(parts)

    def build_system_prompt(self) -> str:
        parts = []
        parts.append(self._get_identity())

        bootstrap = self._get_bootstrap_context()
        if bootstrap:
            parts.append(
                "# Workspace Files\n\n"
                + _clip_context(bootstrap, _MAX_BOOTSTRAP_CONTEXT_CHARS, "workspace files")
            )

        memory_ctx = self.memory.get_memory_context()
        if memory_ctx:
            parts.append(f"# Memory\n\n{memory_ctx}")

        # Skills - progressive loading
        always_skills = self.skills.get_always_skills()
        if always_skills:
            content = self.skills.load_skills_for_context(always_skills)
            if content:
                parts.append(
                    "# Active Skills\n\n"
                    + _clip_context(content, _MAX_ACTIVE_SKILLS_CONTEXT_CHARS, "active skills")
                )

        summary = self.skills.build_skills_summary()
        if summary:
            parts.append(
                "# Skills\n\n"
                "The following skills extend your capabilities. "
                "To use a skill, read its SKILL.md file using the read_file tool.\n\n"
                + _clip_context(summary, _MAX_SKILLS_SUMMARY_CHARS, "skills index")
            )

        return "\n\n---\n\n".join(parts)

    def _get_identity(self) -> str:
        now = datetime.now().strftime("%Y-%m-%d %H:%M (%A)")
        ws = str(self.workspace.resolve())
        system = platform.system()
        runtime = f"{'macOS' if system == 'Darwin' else system} {platform.machine()}, Python {platform.python_version()}"

        custom = self.custom_system_prompt or "You are a helpful personal assistant."

        # Chat mode behavior
        chat_mode = self.agent_config.chat_mode
        if chat_mode == "group":
            mode_section = (
                "\n## Chat Mode: Group\n"
                "You are in a group chat. Only respond when directly addressed or mentioned. "
                "Be mindful of the group context. Announce actions before taking them. "
                "Be careful with memory - don't store personal info about others without consent."
            )
        else:
            mode_section = (
                "\n## Chat Mode: Personal\n"
                "You are in a personal chat. Be proactive, remember details freely, "
                "and manage files without hesitation."
            )

        template = read_text("system.md")
        if template:
            return template.format(
                custom=custom,
                now=now,
                runtime=runtime,
                mode_section=mode_section,
                ws=ws,
                memory_path=f"{ws}/memory/MEMORY.md",
                daily_notes_path=f"{ws}/memory/daily/YYYY-MM-DD.md",
                heartbeat_path=f"{ws}/HEARTBEAT.md",
                skills_path=f"{ws}/skills/",
            )

        return f"""# yacb

{custom}

You have access to tools for file operations, shell commands, web search, messaging, and scheduling.

## Current Time
{now}

## Runtime
{runtime}
{mode_section}

## Workspace
{ws}
- Memory: {ws}/memory/MEMORY.md
- Daily notes: {ws}/memory/daily/YYYY-MM-DD.md
- Heartbeat: {ws}/HEARTBEAT.md
- Skills: {ws}/skills/

## Self-Management
You can read and write files in your workspace. This includes:
- Edit MEMORY.md to update your long-term knowledge
- Edit HEARTBEAT.md to add/remove proactive tasks for yourself
- Create daily notes in memory/daily/ to track your day
- Manage your skills in skills/

When you learn something important, write it down immediately.
When you complete a task from HEARTBEAT.md, remove or check it off.

## Memory Guidelines
- When the user asks you to remember something important (preferences, facts about them, key decisions), use the write_file tool to append it to {ws}/memory/MEMORY.md
- Also use the 'memory' tool to store searchable facts in the knowledge base (remember action)
- When the user asks you to recall something, check both MEMORY.md (read_file) and the knowledge base (memory tool, recall action)
- For daily notes and transient info, write to {ws}/memory/daily/ files

## Tool Usage
- Use web_search whenever you need current/real-time information (news, weather, prices, events, traffic, etc.)
- For normal conversation, respond with text directly - only use the 'message' tool for proactive/cross-channel messaging
- Use the cron tool to schedule reminders and recurring tasks
- Use the conversation_history tool to read long-term chat logs (recent or keyword search), defaulting to current chat
- During heartbeat runs, follow the alive-pulse skill to check for interest updates. Respond with "HEARTBEAT_OK" if nothing noteworthy."""

    async def build_messages_async(
        self,
        history: list[dict[str, Any]],
        current_message: str,
        channel: str | None = None,
        chat_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Build messages with full 3-layer memory context (async)."""
        messages = []
        system_prompt = await self.build_system_prompt_async()
        if channel and chat_id:
            system_prompt += f"\n\n## Current Session\nChannel: {channel}\nChat ID: {chat_id}"
        messages.append({"role": "system", "content": system_prompt})
        messages.extend(history[-_MAX_HISTORY_MESSAGES_IN_PROMPT:])
        messages.append({"role": "user", "content": current_message})
        return messages

    def build_messages(
        self,
        history: list[dict[str, Any]],
        current_message: str,
        channel: str | None = None,
        chat_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Build messages with file-based memory only (sync fallback)."""
        messages = []
        system_prompt = self.build_system_prompt()
        if channel and chat_id:
            system_prompt += f"\n\n## Current Session\nChannel: {channel}\nChat ID: {chat_id}"
        messages.append({"role": "system", "content": system_prompt})
        messages.extend(history[-_MAX_HISTORY_MESSAGES_IN_PROMPT:])
        messages.append({"role": "user", "content": current_message})
        return messages

    def add_tool_result(
        self,
        messages: list[dict[str, Any]],
        tool_call_id: str,
        tool_name: str,
        result: str,
    ) -> list[dict[str, Any]]:
        messages.append({
            "role": "tool",
            "tool_call_id": tool_call_id,
            "name": tool_name,
            "content": result,
        })
        return messages

    def add_assistant_message(
        self,
        messages: list[dict[str, Any]],
        content: str | None,
        tool_calls: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        msg: dict[str, Any] = {"role": "assistant", "content": content or ""}
        if tool_calls:
            msg["tool_calls"] = tool_calls
        messages.append(msg)
        return messages
