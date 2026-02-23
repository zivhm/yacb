"""Shared command help text for chat channels."""

from __future__ import annotations

_COMMAND_ALIASES = {
    "/commands",
    "!commands",
    "/help",
    "!help",
}
_RESET_ALIASES = {
    "/reset",
    "!reset",
}
_TOGGLE_VERBOSE_ALIASES = {
    "/toggle_verbose_logs",
    "!toggle-verbose-logs",
}


def is_commands_request(text: str) -> bool:
    """Return True when text is a command-help request."""
    return text.strip().lower() in _COMMAND_ALIASES


def is_reset_request(text: str) -> bool:
    """Return True when text asks to reset session history."""
    return text.strip().lower() in _RESET_ALIASES


def is_toggle_verbose_request(text: str) -> bool:
    """Return True when text asks to toggle verbose logs."""
    return text.strip().lower() in _TOGGLE_VERBOSE_ALIASES


def get_commands_text(channel: str) -> str:
    """Return command help text for a channel."""
    base = [
        "yacb commands",
        "",
        "Available everywhere:",
        "- /commands (or /help): show this list",
        "- /reset: clear conversation history for this chat (saves important notes first)",
        "- /toggle_verbose_logs: toggle service DEBUG logs",
        "- !<shell command>: run shell directly (example: !docker compose ps -a)",
        "- !model: show active model and tier routing",
        "- !model <provider/model>: set default model",
        "- !tier <light|medium|heavy> <message>: force tier for one message",
        "- !restart: restart confirmation prompt",
        "- !restart now: restart yacb service process",
        "- !update: update confirmation prompt",
        "- !update now: git pull + restart yacb",
        "",
        "Natural language:",
        "- \"remind me in 20 minutes to ...\"",
        "- \"what's on my calendar tomorrow?\"",
    ]

    channel_key = (channel or "").strip().lower()
    if channel_key == "telegram":
        extra = [
            "",
            "Telegram only:",
            "- /start: bot intro",
            "- /debug: toggle model debug footer",
        ]
    elif channel_key == "discord":
        extra = [
            "",
            "Discord only:",
            "- Slash commands supported: /commands, /help, /reset, /toggle_verbose_logs",
            "- Text aliases also work: /commands, /help, /reset, /toggle_verbose_logs",
        ]
    elif channel_key == "whatsapp":
        extra = [
            "",
            "WhatsApp notes:",
            "- Text commands supported: /commands, /help, /reset, /toggle_verbose_logs",
            "- Use !model commands the same way",
        ]
    else:
        extra = []

    return "\n".join(base + extra)
