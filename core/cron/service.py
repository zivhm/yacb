"""Cron service for scheduling agent tasks."""

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Coroutine, Literal

from loguru import logger


@dataclass
class CronSchedule:
    kind: Literal["at", "every", "cron"]
    at_ms: int | None = None
    every_ms: int | None = None
    expr: str | None = None
    tz: str | None = None


@dataclass
class CronPayload:
    kind: Literal["system_event", "agent_turn"] = "agent_turn"
    message: str = ""
    deliver: bool = False
    channel: str | None = None
    to: str | None = None
    direct_delivery: bool = False


@dataclass
class CronJobState:
    next_run_at_ms: int | None = None
    last_run_at_ms: int | None = None
    last_status: Literal["ok", "error", "skipped"] | None = None
    last_error: str | None = None


@dataclass
class CronJob:
    id: str
    name: str
    enabled: bool = True
    schedule: CronSchedule = field(default_factory=lambda: CronSchedule(kind="every"))
    payload: CronPayload = field(default_factory=CronPayload)
    state: CronJobState = field(default_factory=CronJobState)
    created_at_ms: int = 0
    updated_at_ms: int = 0
    delete_after_run: bool = False


def _now_ms() -> int:
    return int(time.time() * 1000)


def _compute_next_run(schedule: CronSchedule, now_ms: int) -> int | None:
    if schedule.kind == "at":
        return schedule.at_ms if schedule.at_ms and schedule.at_ms > now_ms else None
    if schedule.kind == "every":
        if not schedule.every_ms or schedule.every_ms <= 0:
            return None
        return now_ms + schedule.every_ms
    if schedule.kind == "cron" and schedule.expr:
        try:
            from croniter import croniter
            cron = croniter(schedule.expr, time.time())
            return int(cron.get_next() * 1000)
        except Exception:
            return None
    return None


class CronService:
    """Manages and executes scheduled jobs."""

    def __init__(
        self,
        workspace: Path,
        on_job: Callable[[CronJob], Coroutine[Any, Any, str | None]] | None = None,
    ):
        self.workspace = workspace
        self.on_job = on_job
        self._jobs: list[CronJob] = []
        self._timer_task: asyncio.Task | None = None
        self._running = False

    def _load(self) -> None:
        from core.config import load_agent_settings
        self._jobs = []
        settings = load_agent_settings(self.workspace)
        cron_data = settings.get("cron_jobs", {})
        try:
            for j in cron_data.get("jobs", []):
                self._jobs.append(CronJob(
                    id=j["id"], name=j["name"], enabled=j.get("enabled", True),
                    schedule=CronSchedule(**j.get("schedule", {"kind": "every"})),
                    payload=CronPayload(**j.get("payload", {})),
                    state=CronJobState(**j.get("state", {})),
                    created_at_ms=j.get("created_at_ms", 0),
                    updated_at_ms=j.get("updated_at_ms", 0),
                    delete_after_run=j.get("delete_after_run", False),
                ))
        except Exception as e:
            logger.warning(f"Failed to load cron jobs: {e}")

    def _save(self) -> None:
        from core.config import save_agent_settings
        data = {
            "jobs": [
                {
                    "id": j.id, "name": j.name, "enabled": j.enabled,
                    "schedule": {"kind": j.schedule.kind, "at_ms": j.schedule.at_ms,
                                 "every_ms": j.schedule.every_ms, "expr": j.schedule.expr, "tz": j.schedule.tz},
                    "payload": {"kind": j.payload.kind, "message": j.payload.message,
                                "deliver": j.payload.deliver, "channel": j.payload.channel, "to": j.payload.to,
                                "direct_delivery": j.payload.direct_delivery},
                    "state": {"next_run_at_ms": j.state.next_run_at_ms, "last_run_at_ms": j.state.last_run_at_ms,
                              "last_status": j.state.last_status, "last_error": j.state.last_error},
                    "created_at_ms": j.created_at_ms, "updated_at_ms": j.updated_at_ms,
                    "delete_after_run": j.delete_after_run,
                }
                for j in self._jobs
            ]
        }
        save_agent_settings(self.workspace, "cron_jobs", data)

    async def start(self) -> None:
        if self._running:
            logger.debug("Cron service already running; skipping start")
            return
        self._running = True
        self._load()
        now = _now_ms()
        for j in self._jobs:
            if j.enabled:
                j.state.next_run_at_ms = _compute_next_run(j.schedule, now)
        self._save()
        self._arm_timer()
        active = [j for j in self._jobs if j.enabled]
        logger.info(f"Cron service started with {len(active)} active job(s)")
        for j in active:
            eta = (j.state.next_run_at_ms - now) / 1000 if j.state.next_run_at_ms else 0
            logger.info(f"  - '{j.name}' ({j.id}) next in {eta:.0f}s [{j.schedule.kind}]")

    def stop(self) -> None:
        self._running = False
        if self._timer_task:
            self._timer_task.cancel()
            self._timer_task = None

    def _arm_timer(self) -> None:
        if self._timer_task:
            self._timer_task.cancel()
        times = [j.state.next_run_at_ms for j in self._jobs if j.enabled and j.state.next_run_at_ms]
        if not times or not self._running:
            return
        delay_s = max(0, min(times) - _now_ms()) / 1000
        logger.debug(f"Cron: next timer in {delay_s:.1f}s")

        async def tick():
            await asyncio.sleep(delay_s)
            if self._running:
                await self._on_timer()

        self._timer_task = asyncio.create_task(tick())

    async def _on_timer(self) -> None:
        now = _now_ms()
        due = [j for j in self._jobs if j.enabled and j.state.next_run_at_ms and now >= j.state.next_run_at_ms]
        for job in due:
            await self._execute_job(job)
        self._save()
        self._arm_timer()

    async def _execute_job(self, job: CronJob) -> None:
        deliver_to = f" -> {job.payload.channel}:{job.payload.to}" if job.payload.deliver else ""
        logger.info(f"Cron: FIRING '{job.name}' ({job.id}){deliver_to}")
        try:
            if self.on_job:
                await self.on_job(job)
                logger.info(f"Cron: '{job.name}' delivered successfully")
            else:
                logger.warning(f"Cron: '{job.name}' has no on_job callback - message not delivered!")
            job.state.last_status = "ok"
            job.state.last_error = None
        except Exception as e:
            job.state.last_status = "error"
            job.state.last_error = str(e)
            logger.error(f"Cron: '{job.name}' FAILED: {e}")

        job.state.last_run_at_ms = _now_ms()
        job.updated_at_ms = _now_ms()

        if job.schedule.kind == "at":
            if job.delete_after_run:
                self._jobs = [j for j in self._jobs if j.id != job.id]
            else:
                job.enabled = False
                job.state.next_run_at_ms = None
        else:
            job.state.next_run_at_ms = _compute_next_run(job.schedule, _now_ms())

    def list_jobs(self) -> list[CronJob]:
        return sorted(
            [j for j in self._jobs if j.enabled],
            key=lambda j: j.state.next_run_at_ms or float('inf'),
        )

    def add_job(
        self, name: str, schedule: CronSchedule, message: str,
        deliver: bool = False, channel: str | None = None, to: str | None = None,
        delete_after_run: bool = False, direct_delivery: bool = False,
    ) -> CronJob:
        now = _now_ms()
        job = CronJob(
            id=str(uuid.uuid4())[:8], name=name, enabled=True, schedule=schedule,
            payload=CronPayload(kind="agent_turn", message=message, deliver=deliver, channel=channel, to=to, direct_delivery=direct_delivery),
            state=CronJobState(next_run_at_ms=_compute_next_run(schedule, now)),
            created_at_ms=now, updated_at_ms=now, delete_after_run=delete_after_run,
        )
        self._jobs.append(job)
        self._save()
        self._arm_timer()
        logger.info(f"Cron: added '{name}' ({job.id})")
        return job

    def remove_job(self, job_id: str) -> bool:
        before = len(self._jobs)
        self._jobs = [j for j in self._jobs if j.id != job_id]
        if len(self._jobs) < before:
            self._save()
            self._arm_timer()
            return True
        return False
