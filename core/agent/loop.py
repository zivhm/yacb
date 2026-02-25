"""Agent loop: the core processing engine."""

import asyncio
import json
import re
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from litellm import supports_function_calling
from loguru import logger

from core.agent.context import ContextBuilder
from core.agent.onboarding import FirstRunOnboarding
from core.bus.events import InboundMessage, OutboundMessage
from core.bus.queue import MessageBus
from core.channels.commands import (
    is_commands_request,
    is_reset_request,
    is_toggle_verbose_request,
)
from core.config import AgentConfig
from core.providers.base import LLMProvider
from core.providers.registry import find_by_name, normalize_model_name

# Fallback per-1M-token pricing for models litellm doesn't have costs for.
# (input_per_1m, output_per_1m)
_FALLBACK_COSTS: dict[str, tuple[float, float]] = {
    # Gemini
    "gemini-3-flash-preview": (0.50, 3.00),
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.5-pro": (1.25, 10.00),
    "gemini-2.0-flash": (0.10, 0.40),

    # OpenAI
    "gpt-4.1-nano": (0.10, 0.40),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1": (2.00, 8.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),

    # DeepSeek
    "deepseek-chat": (0.27, 1.10),
    "deepseek-reasoner": (0.55, 2.19),
}

_REMINDER_TIME_RE = re.compile(
    r"\b(?:in\s+)?(\d+)\s*(seconds?|secs?|second|minutes?|mins?|minute|hours?|hrs?|hour)\b",
    re.IGNORECASE,
)
_REMINDER_PREFIX_RE = re.compile(r"^.*?\bremind me\b", re.IGNORECASE)

_MAX_TOOL_RESULT_CHARS_FOR_CONTEXT = 4000
_MAX_IDENTICAL_TOOL_ERRORS_PER_TURN = 2
_MAX_RESET_MEMORY_ITEMS = 8
_MAX_RESET_MEMORY_SCAN_MESSAGES = 40
_SESSION_REHYDRATE_LIMIT = 100
_DAILY_FILL_INTERVAL = timedelta(hours=4)
_DAILY_FILL_SETTINGS_KEY = "daily_memory_fill"
_DAILY_FILL_MAX_MESSAGES = 80
_DAILY_FILL_MIN_MESSAGES = 2
_DAILY_LINE_MAX_CHARS = 220
_RESET_IMPORTANT_HINTS = (
    "my name is",
    "i am ",
    "i'm ",
    "call me ",
    "i prefer",
    "prefer ",
    "always ",
    "never ",
    "don't ",
    "do not ",
    "please ",
    "for this skill",
    "use ccxt",
    "use ",
    "timezone",
    "schedule",
    "remind me",
)
_POTENTIAL_SECRET_PATTERNS = (
    re.compile(r"\b(api[_ -]?key|token|secret|password)\b", re.IGNORECASE),
    re.compile(r"\bsk-[A-Za-z0-9]{16,}\b"),
    re.compile(r"\btvly-[A-Za-z0-9_-]{16,}\b"),
)
_BANG_SHELL_RESERVED_PREFIXES = (
    "!model",
    "!restart",
    "!update",
    "!tier",
    "!light",
    "!heavy",
    "!think",
)



def _estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Estimate cost using fallback rates when litellm doesn't know the model."""
    model_lower = model.lower()
    for key, (inp, out) in _FALLBACK_COSTS.items():
        if key in model_lower:
            return (prompt_tokens * inp + completion_tokens * out) / 1_000_000
    return 0.0


def _validate_model_id(model: str) -> tuple[bool, str | None]:
    """Validate provider/model against LiteLLM's catalog when available."""
    normalized = normalize_model_name(model)
    if "/" not in normalized:
        return False, "Expected model format 'provider/model-name'."

    provider = normalized.split("/", 1)[0]
    spec = find_by_name(provider)
    if not spec:
        return False, f"Unknown provider '{provider}'."

    # Gateway providers expose fast-moving catalogs; strict static checks
    # can reject valid new model IDs before LiteLLM metadata catches up.
    if provider == "openrouter":
        model_tail = normalized.split("/", 1)[1]
        if "/" not in model_tail:
            return (
                False,
                "OpenRouter model format should be 'openrouter/<vendor>/<model>'.",
            )
        return True, None

    if provider == "opencode":
        return True, None

    try:
        import litellm
    except Exception:
        return True, None

    provider_key = spec.litellm_prefix or spec.name
    catalog = litellm.models_by_provider.get(provider_key, [])
    if not catalog:
        return True, None

    model_id = normalized.split("/", 1)[1]
    if spec.strip_model_prefix and "/" in model_id:
        model_id = model_id.split("/", 1)[1]

    candidates = {
        normalized,
        model_id,
        f"{provider}/{model_id}",
    }

    catalog_set = {m.lower() for m in catalog}
    if any(c.lower() in catalog_set for c in candidates):
        return True, None

    # Allow matches where catalog entries include provider prefixes.
    if any(m.lower().endswith(f"/{model_id.lower()}") for m in catalog_set):
        return True, None

    return False, f"'{model}' is not a valid model ID for provider '{provider}'."


class AgentLoop:
    """Core agent loop: receives messages, calls LLM, executes tools, responds."""

    def __init__(
        self,
        bus: MessageBus,
        provider: LLMProvider,
        agent_config: AgentConfig,
        workspace: Path,
        tool_registry: Any = None,
        cron_service: Any = None,
        tier_router: Any = None,
        agent_name: str = "default",
    ):
        self.bus = bus
        self.provider = provider
        self.agent_config = agent_config
        self.workspace = workspace
        self.context = ContextBuilder(workspace, agent_config.system_prompt, agent_config=agent_config)
        self.onboarding = FirstRunOnboarding(workspace)
        self.cron_service = cron_service
        self.tier_router = tier_router
        self.agent_name = agent_name
        self._running = False

        # Session history: session_key -> list of messages
        self._sessions: dict[str, list[dict[str, Any]]] = {}
        self._daily_fill_locks: dict[str, asyncio.Lock] = {}

        # Tool registry (set up externally or lazily)
        self.tools = tool_registry

    def _get_history(self, session_key: str) -> list[dict[str, Any]]:
        return self._sessions.setdefault(session_key, [])

    async def _rehydrate_session_history(self, session_key: str, channel: str, chat_id: str) -> None:
        """Load recent user/assistant messages from SQLite after process restart."""
        try:
            from core.storage.db import get_db

            db = get_db(self.workspace)
            rows = await asyncio.wait_for(
                db.get_recent_messages(channel=channel, chat_id=chat_id, limit=_SESSION_REHYDRATE_LIMIT),
                timeout=1.5,
            )
        except Exception as e:
            logger.debug(f"Session rehydrate skipped for {session_key}: {e}")
            return

        if not rows:
            return

        hydrated: list[dict[str, Any]] = []
        for row in rows:
            role = str(row.get("role", "")).strip().lower()
            content = str(row.get("content", "")).strip()
            if role not in {"user", "assistant"} or not content:
                continue
            hydrated.append({"role": role, "content": content})

        if hydrated:
            self._sessions[session_key] = hydrated[-_SESSION_REHYDRATE_LIMIT:]
            logger.info(
                f"Session '{session_key}' rehydrated with {len(self._sessions[session_key])} message(s) from db"
            )

    def _save_exchange(self, session_key: str, user_msg: str, assistant_msg: str) -> None:
        history = self._get_history(session_key)
        history.append({"role": "user", "content": user_msg})
        history.append({"role": "assistant", "content": assistant_msg})
        # Keep last 50 exchanges (100 messages)
        if len(history) > 100:
            self._sessions[session_key] = history[-100:]

    def _append_heavy_daily_note(self, session_key: str, user_msg: str, assistant_msg: str) -> None:
        try:
            channel, chat_id = session_key.split(":", 1)
            now = datetime.now()
            user_summary = self._short_note_text(user_msg, max_chars=90)
            result_summary = self._short_note_text(assistant_msg, max_chars=120)
            line = f"- {now.strftime('%H:%M')} [{channel}:{chat_id}] Heavy update: {user_summary}"
            if result_summary:
                line = f"{line} -> {result_summary}"
            self.context.memory.append_today_note(line)
            self._mark_daily_fill_checkpoint(session_key, source_ts=now.isoformat())
        except Exception as e:
            logger.debug(f"Heavy daily note append skipped for {session_key}: {e}")

    @staticmethod
    def _short_note_text(text: str, max_chars: int = 120) -> str:
        cleaned = " ".join(str(text).split())
        if not cleaned:
            return "No details"
        for sep in (".", "?", "!", "\n"):
            idx = cleaned.find(sep)
            if idx > 0:
                cleaned = cleaned[:idx]
                break
        cleaned = cleaned.strip(" -:,.")
        if not cleaned:
            return "No details"
        if len(cleaned) <= max_chars:
            return cleaned
        return cleaned[: max_chars - 3].rstrip() + "..."

    @staticmethod
    def _parse_iso(value: str) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value)
        except Exception:
            return None

    def _load_daily_fill_settings(self) -> dict[str, Any]:
        try:
            from core.config import load_agent_settings

            settings = load_agent_settings(self.workspace)
            state = settings.get(_DAILY_FILL_SETTINGS_KEY)
            if isinstance(state, dict):
                return state
        except Exception:
            pass
        return {"sessions": {}}

    def _save_daily_fill_settings(self, state: dict[str, Any]) -> None:
        try:
            from core.config import save_agent_settings

            save_agent_settings(self.workspace, _DAILY_FILL_SETTINGS_KEY, state)
        except Exception as e:
            logger.debug(f"Could not persist daily fill settings: {e}")

    def _mark_daily_fill_checkpoint(self, session_key: str, source_ts: str) -> None:
        state = self._load_daily_fill_settings()
        sessions = state.setdefault("sessions", {})
        session_state = sessions.setdefault(session_key, {})
        now_iso = datetime.now().isoformat()
        session_state["last_fill_at"] = now_iso
        session_state["last_check_at"] = now_iso
        session_state["last_fill_source_ts"] = source_ts
        self._save_daily_fill_settings(state)

    async def _maybe_run_periodic_daily_fill(self, channel: str, chat_id: str) -> None:
        session_key = f"{channel}:{chat_id}"
        lock = self._daily_fill_locks.setdefault(session_key, asyncio.Lock())
        if lock.locked():
            return

        async with lock:
            state = self._load_daily_fill_settings()
            sessions = state.setdefault("sessions", {})
            session_state = sessions.setdefault(session_key, {})

            now = datetime.now()
            now_iso = now.isoformat()
            last_check = self._parse_iso(str(session_state.get("last_check_at", "")))
            if last_check is None:
                session_state["last_check_at"] = now_iso
                self._save_daily_fill_settings(state)
                return
            if now - last_check < _DAILY_FILL_INTERVAL:
                return

            from core.storage.db import get_db

            db = get_db(self.workspace)
            rows = await db.get_recent_messages(channel=channel, chat_id=chat_id, limit=_DAILY_FILL_MAX_MESSAGES)
            if not rows:
                session_state["last_check_at"] = now_iso
                self._save_daily_fill_settings(state)
                return

            since_ts = str(session_state.get("last_fill_source_ts", "")).strip()
            if since_ts:
                new_rows = [r for r in rows if str(r.get("timestamp", "")).strip() > since_ts]
            else:
                new_rows = rows

            session_state["last_check_at"] = now_iso
            if len(new_rows) < _DAILY_FILL_MIN_MESSAGES:
                self._save_daily_fill_settings(state)
                return

            significant, note = await self._summarize_significant_changes(new_rows)
            if significant and note:
                line = f"- {now.strftime('%H:%M')} [{session_key}] Periodic update: {note}"
                self.context.memory.append_today_note(line)
                latest_ts = str(new_rows[-1].get("timestamp", "")).strip() or now_iso
                session_state["last_fill_at"] = now_iso
                session_state["last_fill_source_ts"] = latest_ts

            self._save_daily_fill_settings(state)

    async def _summarize_significant_changes(self, rows: list[dict[str, Any]]) -> tuple[bool, str]:
        transcript_parts: list[str] = []
        for row in rows[-30:]:
            ts = str(row.get("timestamp", "")).strip()
            role = str(row.get("role", "")).strip()
            content = self._short_note_text(str(row.get("content", "")), max_chars=180)
            if not content:
                continue
            transcript_parts.append(f"[{ts}] {role}: {content}")

        transcript = "\n".join(transcript_parts)
        if not transcript:
            return False, ""

        model = self.agent_config.model
        if self.tier_router:
            model = self.tier_router.model_for_tier("medium")

        prompt = (
            "Analyze these recent chat changes since the last daily update.\n"
            "Return strict JSON: {\"significant\": boolean, \"note\": string}.\n"
            "Set significant=true only for meaningful updates (decisions, completed tasks, "
            "important blockers, config/model changes, concrete plans).\n"
            "If not significant, return note as empty string.\n"
            f"Keep note under {_DAILY_LINE_MAX_CHARS} characters.\n\n"
            f"Transcript:\n{transcript}"
        )

        try:
            response = await self.provider.chat(
                messages=[
                    {"role": "system", "content": "You produce strict JSON only."},
                    {"role": "user", "content": prompt},
                ],
                model=model,
                max_tokens=220,
                temperature=0.1,
            )
            parsed = self._parse_json_payload(response.content or "")
            if not parsed:
                return False, ""
            significant = bool(parsed.get("significant"))
            note = self._short_note_text(str(parsed.get("note", "")).strip(), max_chars=_DAILY_LINE_MAX_CHARS)
            if not significant:
                return False, ""
            return bool(note), note
        except Exception as e:
            logger.debug(f"Periodic daily fill summarization failed: {e}")
            return False, ""

    @staticmethod
    def _parse_json_payload(text: str) -> dict[str, Any] | None:
        raw = str(text).strip()
        if not raw:
            return None
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass

        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            try:
                parsed = json.loads(raw[start : end + 1])
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                return None
        return None

    async def run(self) -> None:
        self._running = True
        logger.info("Agent loop started")

        while self._running:
            try:
                msg = await asyncio.wait_for(self.bus.consume_inbound(), timeout=1.0)
                try:
                    response = await self._process_message(msg)
                    if response:
                        await self.bus.publish_outbound(response)
                except Exception as e:
                    logger.error(f"Error processing message: {e}")
                    await self.bus.publish_outbound(OutboundMessage(
                        channel=msg.channel,
                        chat_id=msg.chat_id,
                        content=f"Sorry, I encountered an error: {e}",
                    ))
            except asyncio.TimeoutError:
                continue

    def stop(self) -> None:
        self._running = False
        logger.info("Agent loop stopping")

    def clear_session(self, session_key: str) -> int:
        """Clear session history, return number of messages cleared."""
        history = self._sessions.pop(session_key, [])
        return len(history)

    async def snapshot_session_important_info(self, session_key: str) -> int:
        """Persist important recent user messages before a reset.

        Returns number of items saved to long-term memory.
        """
        history = self._get_history(session_key)
        if not history:
            return 0

        seen: set[str] = set()
        important: list[str] = []

        for msg in history[-_MAX_RESET_MEMORY_SCAN_MESSAGES:]:
            if msg.get("role") != "user":
                continue
            text = str(msg.get("content", "")).strip()
            if not self._is_important_for_reset_memory(text):
                continue
            normalized = self._normalize_reset_memory_line(text)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            important.append(normalized)

        if not important:
            return 0

        selected = important[-_MAX_RESET_MEMORY_ITEMS:]
        saved = self._persist_reset_snapshot(session_key, selected)
        try:
            for item in selected:
                await self.context.memory.remember(
                    content=item[:300],
                    category="user_preferences",
                    source="reset_snapshot",
                )
        except Exception:
            pass
        return saved

    async def _handle_model_command(self, raw: str) -> str:
        """Handle !model command. Returns a status/confirmation string."""
        parts = raw.strip().split(None, 1)

        # !model (no args) -> show status
        if len(parts) == 1:
            status = self.tier_router.get_status() if self.tier_router else "Tier router is disabled"
            return f"Current model: {self.agent_config.model}\n{status}"

        # !model <model> -> change default (medium)
        model = normalize_model_name(parts[1])
        ok, err = _validate_model_id(model)
        if not ok:
            return f"Invalid model: {err}"
        self.agent_config.model = model
        if self.tier_router:
            self.tier_router.update_default_model(model)
        self._persist_model_change(default=model)
        status = self.tier_router.get_status() if self.tier_router else "Tier router is disabled"
        return f"Model updated to {model}\n\n{status}"

    @staticmethod
    def _handle_restart_command(raw: str) -> tuple[str, bool]:
        """Handle !restart command. Returns (response_text, should_restart)."""
        parts = raw.strip().split()
        if len(parts) == 1:
            return (
                "Restart warning placeholder only.\n"
                "Send `!restart now` to restart the yacb service.",
                False,
            )

        if len(parts) == 2 and parts[1].lower() == "now":
            return (
                "Restarting yacb now...\n"
                "I will send a wake-up message here once I am back online."
            ), True

        return "Usage: `!restart now`", False

    @staticmethod
    def _handle_update_command(raw: str) -> tuple[str, bool]:
        """Handle !update command. Returns (response_text, should_update)."""
        parts = raw.strip().split()
        if len(parts) == 1:
            return (
                "Update requested.\n"
                "Send `!update now` to confirm git pull + service restart.",
                False,
            )

        if len(parts) == 2 and parts[1].lower() == "now":
            return "Updating yacb now (git pull --ff-only), then restarting...", True

        return "Usage: `!update now`", False

    def _persist_model_change(self, default: str | None = None) -> None:
        """Persist model change to workspace settings.json."""
        from core.config import save_agent_settings

        try:
            if default:
                save_agent_settings(self.workspace, "model", default)

            logger.info("Model change persisted to settings.json")
        except Exception as e:
            logger.error(f"Failed to persist model change: {e}")

    @staticmethod
    def _is_important_for_reset_memory(text: str) -> bool:
        cleaned = text.strip()
        if len(cleaned) < 12:
            return False
        lowered = cleaned.lower()
        if lowered.startswith(("/", "!")):
            return False
        if any(p.search(cleaned) for p in _POTENTIAL_SECRET_PATTERNS):
            return False
        return any(hint in lowered for hint in _RESET_IMPORTANT_HINTS)

    @staticmethod
    def _normalize_reset_memory_line(text: str) -> str:
        line = " ".join(text.split())
        if len(line) > 280:
            line = line[:280].rstrip() + "..."
        return line

    def _persist_reset_snapshot(self, session_key: str, items: list[str]) -> int:
        if not items:
            return 0
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        block = [f"## Reset Snapshot {now} ({session_key})", ""]
        block.extend(f"- {item}" for item in items)
        block_text = "\n".join(block)

        existing = self.context.memory.read_long_term().rstrip()
        merged = f"{existing}\n\n{block_text}\n" if existing else f"{block_text}\n"
        self.context.memory.write_long_term(merged)
        logger.info(f"Reset snapshot saved: {len(items)} item(s) for {session_key}")
        return len(items)

    async def _process_message(self, msg: InboundMessage) -> OutboundMessage | None:
        preview = msg.content[:80] + "..." if len(msg.content) > 80 else msg.content
        logger.info(f"Processing [{msg.channel}:{msg.sender_id}]: {preview}")

        # Handle !model / !restart / !update commands
        first_word = msg.content.strip().split(None, 1)[0].lower() if msg.content.strip() else ""
        if first_word == "!model":
            response_text = await self._handle_model_command(msg.content)
            return OutboundMessage(
                channel=msg.channel, chat_id=msg.chat_id, content=response_text,
            )
        if first_word == "!restart":
            response_text, should_restart = self._handle_restart_command(msg.content)
            metadata = {
                "model": "system/control",
                "tier": "medium",
            }
            if should_restart:
                metadata["restart_requested"] = True
            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content=response_text,
                metadata=metadata,
            )
        if first_word == "!update":
            response_text, should_update = self._handle_update_command(msg.content)
            metadata = {
                "model": "system/control",
                "tier": "medium",
            }
            if should_update:
                metadata["update_requested"] = True
            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content=response_text,
                metadata=metadata,
            )
        if first_word in {"!light", "!heavy", "!think"}:
            tier_hint = "heavy" if first_word in {"!heavy", "!think"} else "light"
            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content=(
                    f"`{first_word}` is deprecated.\n"
                    f"Use `!tier {tier_hint} <message>` instead."
                ),
                metadata={"model": "system/control", "tier": "medium"},
            )

        # Fast path: shell shortcut for messages starting with "!".
        # Reserved bang commands still go through their own handlers.
        bang_shell = await self._handle_bang_shell_command(msg)
        if bang_shell:
            return bang_shell

        onboarding_text = self.onboarding.handle_message(
            channel=msg.channel,
            chat_id=msg.chat_id,
            content=msg.content,
            metadata=msg.metadata,
        )
        if onboarding_text:
            self._save_exchange(msg.session_key, msg.content, onboarding_text)
            await self._log_messages_only(msg, onboarding_text)
            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content=onboarding_text,
                metadata={"model": "system/onboarding", "tier": "medium"},
            )

        # Update tool contexts early (needed by deterministic reminder path).
        if self.tools:
            self._update_tool_contexts(msg)

        # Deterministic reminder path for simple relative reminders.
        direct_reminder = await self._schedule_reminder_deterministically(msg)
        if direct_reminder:
            self._save_exchange(msg.session_key, msg.content, direct_reminder)
            await self._log_messages_only(msg, direct_reminder)
            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content=direct_reminder,
                metadata={"model": "system/reminder-compiler", "tier": "medium"},
            )

        session_key = msg.session_key
        history = self._sessions.get(session_key)
        if history is None:
            self._sessions[session_key] = []
            await self._rehydrate_session_history(session_key, msg.channel, msg.chat_id)
            history = self._sessions[session_key]
        logger.debug(f"Session '{session_key}': {len(history)} messages in history")
        turn_id = uuid.uuid4().hex

        # Route to the right model (and strip any prefix override)
        model = self.agent_config.model
        tier = "medium"
        user_content = msg.content
        medium_model = self.agent_config.model
        if self.tier_router:
            medium_model = self.tier_router.model_for_tier("medium")
            try:
                tier, user_content, model = self.tier_router.route(msg.content)
            except ValueError as e:
                return OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content=str(e),
                    metadata={"model": "system/control", "tier": "medium"},
                )
            logger.debug(f"Router decided: tier={tier}, model={model}")

        # Send a short progress placeholder for medium/heavy turns.
        # The dispatcher already handles this via the existing thinking lifecycle.
        show_progress_placeholder = tier in {"medium", "heavy"}
        if show_progress_placeholder:
            await self.bus.publish_outbound(OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content="working on it...",
                metadata={"thinking": True, "turn_id": turn_id},
            ))

        # Auto-promote to tool-capable model if needed.
        # Skip static capability checks for gateway catalogs where LiteLLM metadata can lag.
        if self.tools:
            model_lower = model.lower()
            dynamic_gateway = model_lower.startswith(("openrouter/", "opencode/"))
            if not dynamic_gateway:
                try:
                    if not supports_function_calling(model):
                        promoted = self.agent_config.model
                        if promoted != model:
                            logger.info(f"Model {model} doesn't support tools, promoting to {promoted}")
                        model = promoted
                except Exception:
                    # If capability detection fails, continue with selected model.
                    pass

        messages = await self.context.build_messages_async(
            history=history,
            current_message=user_content,
            channel=msg.channel,
            chat_id=msg.chat_id,
        )

        # Agent loop
        iteration = 0
        final_content = None
        tool_call_counts: dict[str, int] = {}
        used_tools: set[str] = set()
        cron_add_attempted = False
        cron_add_succeeded = False
        max_same_tool = 8
        repeated_tool_errors: dict[tuple[str, str], int] = {}
        blocked_tools_due_to_errors: set[str] = set()
        total_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        failover_attempted = False
        logger.debug(f"Using model: {model}")

        while iteration < self.agent_config.max_iterations:
            iteration += 1

            logger.debug(f"LLM call #{iteration}/{self.agent_config.max_iterations} ({len(messages)} messages)")
            response = await self.provider.chat(
                messages=messages,
                tools=self.tools.get_definitions() if self.tools else None,
                model=model,
                max_tokens=self.agent_config.max_tokens,
                temperature=self.agent_config.temperature,
            )
            # Accumulate token usage
            if response.usage:
                for k in total_usage:
                    total_usage[k] += response.usage.get(k, 0)

            if (
                response.finish_reason == "error"
                and not failover_attempted
                and model != medium_model
            ):
                logger.warning(
                    f"Tier model '{model}' failed for this turn; retrying once with medium '{medium_model}'"
                )
                model = medium_model
                failover_attempted = True
                continue

            logger.debug(
                f"LLM response: has_tools={response.has_tool_calls}, "
                f"content_len={len(response.content or '')}, "
                f"tool_calls={[tc.name for tc in (response.tool_calls or [])]}"
            )

            if response.has_tool_calls:
                tool_call_dicts = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments),
                        },
                    }
                    for tc in response.tool_calls
                ]
                messages = self.context.add_assistant_message(
                    messages, response.content, tool_call_dicts
                )

                for tool_call in response.tool_calls:
                    used_tools.add(tool_call.name)
                    tool_call_counts[tool_call.name] = tool_call_counts.get(tool_call.name, 0) + 1
                    tool_was_executed = False
                    if tool_call.name in blocked_tools_due_to_errors:
                        logger.warning(
                            f"Tool '{tool_call.name}' blocked for this turn after repeated identical errors"
                        )
                        result = (
                            f"[Tool blocked for this turn: '{tool_call.name}' kept returning the same "
                            "error. Use available results and respond to the user.]"
                        )
                    elif tool_call_counts[tool_call.name] > max_same_tool:
                        logger.warning(
                            f"Tool '{tool_call.name}' called {tool_call_counts[tool_call.name]} "
                            f"times (limit {max_same_tool}), returning limit notice"
                        )
                        result = (
                            f"[Tool call limit reached: '{tool_call.name}' has been called "
                            f"{max_same_tool} times. Summarize what you have and respond to the user.]"
                        )
                    else:
                        args_str = json.dumps(tool_call.arguments, ensure_ascii=False)
                        logger.info(f"Tool: {tool_call.name}({args_str[:200]})")
                        result = await self.tools.execute(tool_call.name, tool_call.arguments)
                        tool_was_executed = True
                        if tool_call.name == "cron" and tool_call.arguments.get("action") == "add":
                            cron_add_attempted = True
                            if result.startswith("Created"):
                                cron_add_succeeded = True
                        logger.debug(f"Tool result ({tool_call.name}): {str(result)[:300]}")

                    if tool_was_executed:
                        signature = self._canonical_tool_error(result)
                        if signature:
                            key = (tool_call.name, signature)
                            seen = repeated_tool_errors.get(key, 0) + 1
                            repeated_tool_errors[key] = seen
                            if seen >= _MAX_IDENTICAL_TOOL_ERRORS_PER_TURN:
                                blocked_tools_due_to_errors.add(tool_call.name)
                                logger.warning(
                                    f"Tool '{tool_call.name}' produced the same error {seen} times; "
                                    "blocking further calls this turn"
                                )

                    result_for_context = self._truncate_tool_result_for_context(
                        result,
                        max_chars=_MAX_TOOL_RESULT_CHARS_FOR_CONTEXT,
                    )
                    messages = self.context.add_tool_result(
                        messages, tool_call.id, tool_call.name, result_for_context
                    )
            else:
                final_content = response.content
                break

        reminder_requested = self._is_reminder_request(user_content)
        if not (final_content or "").strip():
            forced = await self._force_final_text(messages, model)
            if forced:
                final_content = forced

        if reminder_requested and not cron_add_succeeded:
            fallback = await self._auto_schedule_simple_reminder(user_content)
            if fallback:
                logger.warning("Reminder guard: no successful cron add; used fallback scheduler")
                final_content = fallback
                cron_add_succeeded = True

        if reminder_requested and not cron_add_succeeded:
            reason = "No successful cron add was performed"
            if cron_add_attempted:
                reason = "Cron add was attempted but failed"
            logger.warning(f"Reminder guard: {reason}")
            final_content = (
                "I couldn't schedule that reminder yet. Please rephrase with an exact delay "
                "(example: 'remind me in 5 minutes to turn off the stove')."
            )

        if not (final_content or "").strip():
            final_content = "I've completed processing but have no response to give."

        preview = final_content[:120] + "..." if len(final_content) > 120 else final_content
        logger.info(f"Response [{msg.channel}:{msg.sender_id}]: {preview}")

        if tier == "heavy":
            self._append_heavy_daily_note(session_key, msg.content, final_content)
        self._save_exchange(session_key, msg.content, final_content)

        # Log to SQLite in background so response delivery never blocks on DB init/IO.
        self._schedule_db_logging(
            msg=msg,
            final_content=final_content,
            model=model,
            tier=tier,
            total_usage=total_usage,
        )

        out_metadata = dict(msg.metadata or {})
        out_metadata["model"] = model
        if tier:
            out_metadata["tier"] = tier
        if show_progress_placeholder:
            out_metadata["clear_thinking"] = True
            out_metadata["turn_id"] = turn_id

        return OutboundMessage(
            channel=msg.channel,
            chat_id=msg.chat_id,
            content=final_content,
            metadata=out_metadata,
        )

    async def _schedule_reminder_deterministically(self, msg: InboundMessage) -> str | None:
        """Schedule simple reminders before LLM to guarantee reliability."""
        if not self.tools or "cron" not in self.tools.tool_names:
            return None
        parsed = self._parse_simple_relative_reminder(msg.content)
        if not parsed:
            return None

        in_seconds, reminder_message = parsed
        result = await self.tools.execute(
            "cron",
            {
                "action": "add",
                "message": reminder_message,
                "in_seconds": in_seconds,
            },
        )
        if not result.startswith("Created"):
            logger.warning(f"Deterministic reminder scheduling failed: {result}")
            return None

        fire_at = datetime.now() + timedelta(seconds=in_seconds)
        fire_local = fire_at.strftime("%H:%M:%S")
        logger.info(
            "Reminder compiler: scheduled one-time reminder "
            f"for {msg.channel}:{msg.chat_id} in {in_seconds}s"
        )
        return (
            f"Reminder set for {fire_local} "
            f"(in {in_seconds} seconds): {reminder_message}"
        )

    async def _handle_bang_shell_command(self, msg: InboundMessage) -> OutboundMessage | None:
        """Execute `!<shell command>` directly without an LLM call."""
        raw = (msg.content or "").strip()
        if not raw.startswith("!"):
            return None

        lowered = raw.lower()
        if lowered in {"!", "!!"}:
            return None

        if any(lowered.startswith(prefix) for prefix in _BANG_SHELL_RESERVED_PREFIXES):
            return None
        if is_commands_request(raw) or is_reset_request(raw) or is_toggle_verbose_request(raw):
            return None

        if not self.tools or "exec" not in self.tools.tool_names:
            text = "Shell shortcut unavailable: exec tool is not enabled for this agent."
            self._save_exchange(msg.session_key, msg.content, text)
            await self._log_messages_only(msg, text)
            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content=text,
                metadata={"model": "system/shell", "tier": "medium"},
            )

        command = raw[1:].strip()
        if not command:
            return None

        logger.info(f"Bang shell command [{msg.channel}:{msg.chat_id}]: {command[:120]}")
        result = await self.tools.execute("exec", {"command": command})
        final = f"$ {command}\n{result}"
        self._save_exchange(msg.session_key, msg.content, final)
        await self._log_messages_only(msg, final)
        return OutboundMessage(
            channel=msg.channel,
            chat_id=msg.chat_id,
            content=final,
            metadata={"model": "system/shell", "tier": "medium"},
        )

    async def _log_messages_only(self, msg: InboundMessage, assistant_text: str) -> None:
        """Persist user/assistant exchange when no model call happened."""
        self._schedule_db_logging(
            msg=msg,
            final_content=assistant_text,
            model="system/reminder-compiler",
            tier="medium",
            total_usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        )

    async def _force_final_text(self, messages: list[dict[str, Any]], model: str) -> str | None:
        """Attempt one tool-free finalization call when model returns empty content."""
        try:
            follow_up = list(messages)
            follow_up.append({
                "role": "user",
                "content": (
                    "Provide a final reply to the user based on the conversation so far. "
                    "Do not call tools in this reply."
                ),
            })
            response = await self.provider.chat(
                messages=follow_up,
                model=model,
                max_tokens=self.agent_config.max_tokens,
                temperature=0.2,
            )
            content = (response.content or "").strip()
            if content:
                logger.warning("Recovered empty final response via tool-free finalization call")
                return content
        except Exception as e:
            logger.warning(f"Failed finalization fallback: {e}")
        return None

    @staticmethod
    def _truncate_tool_result_for_context(result: str, max_chars: int) -> str:
        """Cap tool output added back into the prompt to control token growth."""
        text = str(result)
        if len(text) <= max_chars:
            return text
        dropped = len(text) - max_chars
        return f"{text[:max_chars]}\n... [truncated {dropped} chars before next LLM turn]"

    @staticmethod
    def _canonical_tool_error(result: str) -> str | None:
        """Normalize tool errors so repeated failures can be detected per turn."""
        text = str(result).strip()
        if not text:
            return None

        if text.lower().startswith("error:"):
            return text.splitlines()[0][:240]

        if text.startswith("{") and "\"error\"" in text.lower():
            try:
                payload = json.loads(text)
            except Exception:
                payload = None
            if isinstance(payload, dict):
                err = str(payload.get("error", "")).strip()
                if err:
                    return f"json_error:{err.splitlines()[0][:220]}"

        if "STDERR:" in text and "Exit code:" in text:
            stderr = text.split("STDERR:", 1)[1]
            first_line = ""
            for line in stderr.splitlines():
                candidate = line.strip()
                if candidate:
                    first_line = candidate
                    break
            if first_line:
                return f"stderr:{first_line[:220]}"

        return None

    @staticmethod
    def _is_reminder_request(text: str) -> bool:
        lower = text.lower()
        return "remind me" in lower or "set a reminder" in lower

    @staticmethod
    def _parse_simple_relative_reminder(text: str) -> tuple[int, str] | None:
        """Parse simple reminders like 'remind me in 5 minutes to X'."""
        if not AgentLoop._is_reminder_request(text):
            return None

        match = _REMINDER_TIME_RE.search(text)
        if not match:
            return None

        value = int(match.group(1))
        unit = match.group(2).lower()
        if value <= 0:
            return None

        if unit.startswith(("hour", "hr")):
            in_seconds = value * 3600
        elif unit.startswith(("minute", "min")):
            in_seconds = value * 60
        else:
            in_seconds = value

        original = text.strip()

        # Prefer content after the detected time phrase (more accurate than global marker search).
        start_idx, end_idx = match.span()
        after_time = original[end_idx:].strip(" ,.;:!?-\"'()[]{}")
        before_time = original[:start_idx].strip(" ,.;:!?-\"'()[]{}")
        reminder_message = AgentLoop._extract_reminder_message(after_time, before_time)
        return in_seconds, reminder_message

    @staticmethod
    def _extract_reminder_message(after_time: str, before_time: str) -> str:
        """Extract reminder content from around the detected time expression."""
        message = after_time.strip(" ,.;:!?-\"'()[]{}")
        if message and any(ch.isalnum() for ch in message):
            lowered = message.lower()
            for prefix in ("to ", "about ", "that ", "for "):
                if lowered.startswith(prefix):
                    message = message[len(prefix):].strip()
                    break
            return (message or "Reminder")[:200]

        # Fallback for forms like "remind me to buy milk in 5 minutes".
        before = _REMINDER_PREFIX_RE.sub("", before_time).strip()
        # Handle phrasing like "remind me to X in like 3 minutes".
        before = re.sub(r"\b(?:in(?:\s+like)?|after)\s*$", "", before, flags=re.IGNORECASE).strip()
        lowered = before.lower()
        for prefix in ("to ", "about ", "that ", "for "):
            if lowered.startswith(prefix):
                before = before[len(prefix):].strip()
                break
        before = before.strip(" ,.;:!?-\"'()[]{}")
        return (before or "Reminder")[:200]

    async def _auto_schedule_simple_reminder(self, text: str) -> str | None:
        """Fallback path when model promised a reminder but never called cron."""
        if not self.tools or "cron" not in self.tools.tool_names:
            return None

        parsed = self._parse_simple_relative_reminder(text)
        if not parsed:
            return None

        in_seconds, reminder_message = parsed
        result = await self.tools.execute(
            "cron",
            {
                "action": "add",
                "message": reminder_message,
                "in_seconds": in_seconds,
            },
        )
        if result.startswith("Created"):
            return (
                f"Reminder scheduled now for '{reminder_message}' "
                f"(in {in_seconds} seconds)."
            )
        logger.warning(f"Reminder fallback scheduling failed: {result}")
        return None

    def _schedule_db_logging(
        self,
        msg: InboundMessage,
        final_content: str,
        model: str,
        tier: str,
        total_usage: dict[str, int],
    ) -> None:
        """Schedule best-effort DB logging without blocking user response."""
        try:
            asyncio.create_task(
                self._persist_db_logging(
                    msg=msg,
                    final_content=final_content,
                    model=model,
                    tier=tier,
                    total_usage=total_usage,
                )
            )
        except Exception as e:
            logger.warning(f"Failed to schedule db logging task: {e}")

    async def _persist_db_logging(
        self,
        msg: InboundMessage,
        final_content: str,
        model: str,
        tier: str,
        total_usage: dict[str, int],
    ) -> None:
        """Persist chat logs/token usage with short timeouts to avoid stalls."""
        try:
            from core.storage.db import get_db

            db = get_db(self.workspace)
            await asyncio.wait_for(
                db.log_message(msg.channel, msg.chat_id, msg.sender_id, "user", msg.content),
                timeout=1.0,
            )
            await asyncio.wait_for(
                db.log_message(msg.channel, msg.chat_id, "assistant", "assistant", final_content),
                timeout=1.0,
            )

            if total_usage["total_tokens"] > 0:
                cost = 0.0
                try:
                    from litellm import completion_cost

                    cost = completion_cost(
                        model=model,
                        prompt_tokens=total_usage["prompt_tokens"],
                        completion_tokens=total_usage["completion_tokens"],
                    )
                except Exception:
                    cost = _estimate_cost(
                        model, total_usage["prompt_tokens"], total_usage["completion_tokens"]
                    )

                await asyncio.wait_for(
                    db.log_token_usage(
                        channel=msg.channel,
                        chat_id=msg.chat_id,
                        model=model,
                        tier=tier,
                        prompt_tokens=total_usage["prompt_tokens"],
                        completion_tokens=total_usage["completion_tokens"],
                        total_tokens=total_usage["total_tokens"],
                        cost=cost,
                    ),
                    timeout=1.0,
                )
                logger.debug(
                    f"Usage: {total_usage['total_tokens']} tokens "
                    f"({total_usage['prompt_tokens']}in/{total_usage['completion_tokens']}out) "
                    f"${cost:.6f} [{model}]"
                )

            await self._maybe_run_periodic_daily_fill(msg.channel, msg.chat_id)
        except Exception as e:
            logger.warning(f"DB logging failed for {msg.channel}:{msg.chat_id}: {e}")

    def _update_tool_contexts(self, msg: InboundMessage) -> None:
        """Update tool contexts with current channel/chat info."""
        message_tool = self.tools.get("message")
        if message_tool and hasattr(message_tool, "set_context"):
            message_tool.set_context(msg.channel, msg.chat_id)

        cron_tool = self.tools.get("cron")
        if cron_tool and hasattr(cron_tool, "set_context"):
            cron_tool.set_context(msg.channel, msg.chat_id)

        usage_tool = self.tools.get("token_usage")
        if usage_tool and hasattr(usage_tool, "set_context"):
            usage_tool.set_context(chat_id=msg.chat_id)

        history_tool = self.tools.get("conversation_history")
        if history_tool and hasattr(history_tool, "set_context"):
            history_tool.set_context(channel=msg.channel, chat_id=msg.chat_id)

    async def process_direct(self, content: str, channel: str = "system", chat_id: str = "direct") -> str:
        """Process a message directly (for cron/heartbeat)."""
        msg = InboundMessage(channel=channel, sender_id="system", chat_id=chat_id, content=content)
        response = await self._process_message(msg)
        return response.content if response else ""
