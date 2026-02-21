"""Cron tool for scheduling reminders and tasks."""

from typing import Any

from loguru import logger

from core.cron.service import CronSchedule, CronService
from core.tools.base import Tool


class CronTool(Tool):
    """Schedule reminders and recurring tasks."""

    def __init__(self, cron_service: CronService):
        self._cron = cron_service
        self._channel = ""
        self._chat_id = ""

    def set_context(self, channel: str, chat_id: str) -> None:
        self._channel = channel
        self._chat_id = chat_id

    @property
    def name(self) -> str:
        return "cron"

    @property
    def description(self) -> str:
        return (
            "Schedule reminders and recurring tasks. Actions: add, list, remove. "
            "For one-time reminders use in_seconds (e.g. 120 for 2 minutes). "
            "For recurring use every_seconds or cron_expr."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["add", "list", "remove"], "description": "Action to perform"},
                "message": {"type": "string", "description": "Reminder message (for add)"},
                "in_seconds": {"type": "integer", "description": "One-time reminder: fire once after this many seconds (e.g. 120 = 2 minutes)"},
                "every_seconds": {"type": "integer", "description": "Recurring: repeat every N seconds"},
                "cron_expr": {"type": "string", "description": "Cron expression like '0 9 * * *'"},
                "job_id": {"type": "string", "description": "Job ID (for remove)"},
                "direct": {"type": "boolean", "description": "If true, deliver message directly without LLM processing (default: true for one-time reminders)"},
            },
            "required": ["action"],
        }

    async def execute(
        self, action: str, message: str = "", in_seconds: int | None = None,
        every_seconds: int | None = None, cron_expr: str | None = None,
        job_id: str | None = None, direct: bool | None = None, **kwargs: Any,
    ) -> str:
        if action == "add":
            return self._add(message, in_seconds, every_seconds, cron_expr, direct)
        elif action == "list":
            return self._list()
        elif action == "remove":
            return self._remove(job_id)
        return f"Unknown action: {action}"

    def _add(self, message: str, in_seconds: int | None, every_seconds: int | None, cron_expr: str | None, direct: bool | None = None) -> str:
        if not message:
            return "Error: message is required"
        if not self._channel or not self._chat_id:
            return "Error: no session context"

        import time
        delete_after = False

        if in_seconds:
            # One-time reminder
            at_ms = int(time.time() * 1000) + (in_seconds * 1000)
            schedule = CronSchedule(kind="at", at_ms=at_ms)
            delete_after = True
        elif every_seconds:
            schedule = CronSchedule(kind="every", every_ms=every_seconds * 1000)
        elif cron_expr:
            schedule = CronSchedule(kind="cron", expr=cron_expr)
        else:
            return "Error: provide in_seconds, every_seconds, or cron_expr"

        # Default: direct delivery for one-time reminders
        use_direct = direct if direct is not None else bool(in_seconds)

        job = self._cron.add_job(
            name=message[:30], schedule=schedule, message=message,
            deliver=True, channel=self._channel, to=self._chat_id,
            delete_after_run=delete_after, direct_delivery=use_direct,
        )
        kind = "one-time" if in_seconds else "recurring"
        eta = f" (fires in {in_seconds}s)" if in_seconds else ""
        logger.info(f"Cron tool: scheduled {kind} job '{job.name}' ({job.id}) -> {self._channel}:{self._chat_id}{eta}")
        return f"Created {kind} job '{job.name}' (id: {job.id})"

    def _list(self) -> str:
        jobs = self._cron.list_jobs()
        if not jobs:
            return "No scheduled jobs."
        lines = [f"- {j.name} (id: {j.id}, {j.schedule.kind})" for j in jobs]
        return "Scheduled jobs:\n" + "\n".join(lines)

    def _remove(self, job_id: str | None) -> str:
        if not job_id:
            return "Error: job_id is required"
        if self._cron.remove_job(job_id):
            return f"Removed job {job_id}"
        return f"Job {job_id} not found"
