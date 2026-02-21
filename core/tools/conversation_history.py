"""Conversation history tool backed by SQLite message logs."""

from pathlib import Path
from typing import Any

from core.tools.base import Tool


class ConversationHistoryTool(Tool):
    """Read recent or matching messages from persistent conversation logs."""

    name = "conversation_history"
    description = (
        "Read long-term conversation logs from SQLite. "
        "Actions: recent (latest messages), search (keyword/full-text search). "
        "Defaults to current chat for efficiency."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["recent", "search"],
                "description": "Action to perform",
            },
            "query": {
                "type": "string",
                "description": "Search text for action='search'",
            },
            "limit": {
                "type": "integer",
                "description": "Max rows to return (1-50, default 10)",
            },
            "chat_only": {
                "type": "boolean",
                "description": "If true (default), only read current chat history.",
            },
        },
        "required": ["action"],
    }

    def __init__(self, workspace: Path):
        self._workspace = workspace
        self._channel: str | None = None
        self._chat_id: str | None = None

    def set_context(self, channel: str | None = None, chat_id: str | None = None, **_: Any) -> None:
        self._channel = channel
        self._chat_id = chat_id

    async def execute(
        self,
        action: str,
        query: str = "",
        limit: int = 10,
        chat_only: bool = True,
        **kwargs: Any,
    ) -> str:
        from core.storage.db import get_db

        limit = max(1, min(int(limit), 50))

        channel = self._channel if chat_only else None
        chat_id = self._chat_id if chat_only else None
        if chat_only and (not channel or not chat_id):
            return "Error: no session context available for chat_only query"

        db = get_db(self._workspace)
        if action == "recent":
            rows = await db.get_recent_messages(channel=channel, chat_id=chat_id, limit=limit)
        elif action == "search":
            if not query.strip():
                return "Error: query is required for action='search'"
            rows = await db.search_messages(
                query=query.strip(),
                limit=limit,
                channel=channel,
                chat_id=chat_id,
            )
        else:
            return f"Error: unknown action '{action}'"

        if not rows:
            scope = "current chat" if chat_only else "all chats"
            return f"No conversation history found for {scope}."

        lines: list[str] = []
        for row in rows:
            timestamp = str(row.get("timestamp", ""))[:19].replace("T", " ")
            role = str(row.get("role", "unknown"))
            row_channel = str(row.get("channel", ""))
            row_chat = str(row.get("chat_id", ""))
            content = self._compact(str(row.get("content", "")))
            if chat_only:
                lines.append(f"[{timestamp}] {role}: {content}")
            else:
                lines.append(f"[{timestamp}] {row_channel}:{row_chat} {role}: {content}")
        return "\n".join(lines)

    @staticmethod
    def _compact(text: str, max_chars: int = 180) -> str:
        text = " ".join(text.split())
        if len(text) <= max_chars:
            return text
        return text[: max_chars - 3].rstrip() + "..."

