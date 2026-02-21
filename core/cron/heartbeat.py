"""Heartbeat service - periodic HEARTBEAT.md checker with delivery."""

import asyncio
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Coroutine

from loguru import logger


class HeartbeatService:
    """Periodically reads HEARTBEAT.md, triggers agent, and delivers updates."""

    def __init__(
        self,
        workspace: Path,
        interval_minutes: int = 240,
        on_heartbeat: Callable[[str], Coroutine[Any, Any, str]] | None = None,
        on_deliver: Callable[[str], Coroutine[Any, Any, None]] | None = None,
        active_hours_start: str = "08:00",
        active_hours_end: str = "22:00",
        suppress_empty: bool = True,
    ):
        self.workspace = workspace
        self.heartbeat_file = workspace / "HEARTBEAT.md"
        self.interval_minutes = interval_minutes
        self.on_heartbeat = on_heartbeat
        self.on_deliver = on_deliver
        self.active_hours_start = active_hours_start
        self.active_hours_end = active_hours_end
        self.suppress_empty = suppress_empty
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info(f"Heartbeat service started (every {self.interval_minutes}min)")

    def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None

    def _is_within_active_hours(self) -> bool:
        """Check if the current time falls within the configured active hours."""
        now = datetime.now()
        try:
            start_h, start_m = map(int, self.active_hours_start.split(":"))
            end_h, end_m = map(int, self.active_hours_end.split(":"))
        except (ValueError, AttributeError):
            return True  # If parsing fails, default to active

        current_minutes = now.hour * 60 + now.minute
        start_minutes = start_h * 60 + start_m
        end_minutes = end_h * 60 + end_m

        if start_minutes <= end_minutes:
            return start_minutes <= current_minutes < end_minutes
        else:
            # Wraps midnight (e.g. 22:00 - 06:00)
            return current_minutes >= start_minutes or current_minutes < end_minutes

    def _should_suppress(self, response: str) -> bool:
        """Check if the response should be suppressed (HEARTBEAT_OK with minimal text)."""
        if not self.suppress_empty:
            return False
        cleaned = response.strip()
        # Suppress if response is just HEARTBEAT_OK (possibly with whitespace/punctuation)
        if re.match(r"^HEARTBEAT_OK[.!]?$", cleaned):
            return True
        # Also suppress if HEARTBEAT_OK is present and the rest is very short
        if "HEARTBEAT_OK" in cleaned:
            without = cleaned.replace("HEARTBEAT_OK", "").strip()
            if len(without) < 30:
                return True
        return False

    async def _loop(self) -> None:
        while self._running:
            try:
                await asyncio.sleep(self.interval_minutes * 60)
                if not self._running:
                    break
                await self._check()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Heartbeat error: {e}")

    async def _check(self) -> None:
        if not self._is_within_active_hours():
            logger.debug("Heartbeat: outside active hours, skipping")
            return

        if not self.heartbeat_file.exists():
            return

        content = self.heartbeat_file.read_text(encoding="utf-8").strip()
        if not content:
            return

        # Skip if only comments or headers with no tasks
        lines = [
            line.strip()
            for line in content.split("\n")
            if line.strip() and not line.strip().startswith("#")
        ]
        if not lines:
            return

        logger.info(f"Heartbeat: found {len(lines)} actionable lines")

        if self.on_heartbeat:
            prompt = (
                "[HEARTBEAT] The following tasks are in your HEARTBEAT.md file. "
                "Review them and take action on any that are due or relevant now.\n\n"
                f"{content}"
            )
            response = await self.on_heartbeat(prompt)

            if response and self._should_suppress(response):
                logger.info("Heartbeat: response suppressed (HEARTBEAT_OK)")
                return

            if response and self.on_deliver:
                logger.info(f"Heartbeat: delivering response ({len(response)} chars)")
                await self.on_deliver(response)
            elif response:
                logger.info(f"Heartbeat response (no delivery target): {response[:100]}...")
