"""Token usage and cost tracking tool."""

from pathlib import Path
from typing import Any

from core.tools.base import Tool


class TokenUsageTool(Tool):
    """Report token usage and estimated costs."""

    name = "token_usage"
    description = (
        "Get token usage summary and estimated costs. "
        "Shows per-model breakdown with token counts and costs. "
        "Use period='today' for today, 'week' for last 7 days, 'month' for last 30 days, 'all' for all time."
    )
    parameters = {
        "type": "object",
        "properties": {
            "period": {
                "type": "string",
                "description": "Time period: 'today', 'week', 'month', or 'all'",
                "enum": ["today", "week", "month", "all"],
            },
            "chat_only": {
                "type": "boolean",
                "description": "If true, show usage for current chat only. Default false (all chats).",
            },
        },
        "required": [],
    }

    def __init__(self, workspace: Path):
        self._workspace = workspace
        self._chat_id: str | None = None

    def set_context(self, chat_id: str | None = None, **_: Any) -> None:
        self._chat_id = chat_id

    async def execute(self, period: str = "month", chat_only: bool = False) -> str:
        from core.storage.db import get_db

        days_map = {"today": 1, "week": 7, "month": 30, "all": 36500}
        days = days_map.get(period, 30)

        db = get_db(self._workspace)
        chat_id = self._chat_id if chat_only else None

        models = await db.get_usage_summary(chat_id=chat_id, days=days)
        totals = await db.get_usage_total(days=days)

        if not models or totals["calls"] == 0:
            return f"No usage data found for the last {period}."

        lines = [f"**Token Usage — {period}**\n"]

        for m in models:
            cost_str = f"${m['cost']:.4f}" if m["cost"] > 0 else "n/a"
            lines.append(
                f"• **{m['model']}** ({m['tier'] or 'default'}): "
                f"{m['total_tokens']:,} tokens "
                f"({m['prompt_tokens']:,} in / {m['completion_tokens']:,} out) — "
                f"{cost_str} — {m['calls']} calls"
            )

        lines.append("")
        total_cost = f"${totals['cost']:.4f}" if totals["cost"] > 0 else "n/a"
        lines.append(
            f"**Total**: {totals['total_tokens']:,} tokens — {total_cost} — {totals['calls']} calls"
        )

        if chat_only:
            lines.append("\n_(filtered to current chat)_")

        return "\n".join(lines)
