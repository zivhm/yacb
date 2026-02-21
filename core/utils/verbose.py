"""Verbose logging toggle — persists state to the agent workspace settings.json."""

import sys
from pathlib import Path

from loguru import logger

_verbose_enabled = False
_verbose_sink_id: int | None = None


def is_verbose() -> bool:
    return _verbose_enabled


def load_verbose_state(workspace: Path) -> bool:
    """Load persisted state on startup. Returns current state."""
    global _verbose_enabled
    from core.config import load_agent_settings
    settings = load_agent_settings(workspace)
    verbose_data = settings.get("verbose_logs", {})
    _verbose_enabled = bool(verbose_data.get("enabled", False))
    if _verbose_enabled:
        _apply_verbose(True)
    return _verbose_enabled


def toggle_verbose(workspace: Path) -> bool:
    """Toggle verbose logging. Returns new state."""
    global _verbose_enabled
    _verbose_enabled = not _verbose_enabled
    _save_state(workspace)
    _apply_verbose(_verbose_enabled)
    logger.info(f"Verbose logging {'ON' if _verbose_enabled else 'OFF'}")
    return _verbose_enabled


def _save_state(workspace: Path) -> None:
    from core.config import save_agent_settings
    save_agent_settings(workspace, "verbose_logs", {"enabled": _verbose_enabled})


def _apply_verbose(enabled: bool) -> None:
    """Switch loguru between INFO and DEBUG."""
    global _verbose_sink_id
    if enabled:
        if _verbose_sink_id is None:
            _verbose_sink_id = logger.add(
                sys.stderr,
                level="DEBUG",
                format=(
                    "<dim>{time:HH:mm:ss}</dim> | <level>{level: <8}</level> | "
                    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
                    "<level>{message}</level>"
                ),
                filter=lambda record: record["level"].name == "DEBUG",
            )
    else:
        if _verbose_sink_id is not None:
            logger.remove(_verbose_sink_id)
            _verbose_sink_id = None
