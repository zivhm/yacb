"""Shell execution tool."""

import asyncio
import os
import re
import shlex
from pathlib import Path
from typing import Any

from core.tools.base import Tool
from core.utils.security import resolve_safe_path

DENY_PATTERNS = [
    r"\brm\s+-[rf]{1,2}\b",
    r"\bdel\s+/[fq]\b",
    r"\brmdir\s+/s\b",
    r"\b(format|mkfs|diskpart)\b",
    r"\bdd\s+if=",
    r">\s*/dev/sd",
    r"\b(shutdown|reboot|poweroff)\b",
    r":\(\)\s*\{.*\};\s*:",
]


class ExecTool(Tool):
    """Execute shell commands."""

    def __init__(self, timeout: int = 60, working_dir: str | None = None, restrict_to_workspace: bool = False):
        self.timeout = timeout
        self.working_dir = working_dir
        self.restrict_to_workspace = restrict_to_workspace

    @property
    def name(self) -> str:
        return "exec"

    @property
    def description(self) -> str:
        return "Execute a shell command and return its output."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "The shell command to execute"},
                "working_dir": {"type": "string", "description": "Optional working directory"},
            },
            "required": ["command"],
        }

    async def execute(self, command: str, working_dir: str | None = None, **kwargs: Any) -> str:
        workspace_dir = Path(self.working_dir or os.getcwd()).expanduser().resolve()
        cwd = Path(working_dir or str(workspace_dir)).expanduser().resolve()

        # Safety guard
        cmd_lower = command.strip().lower()
        for pattern in DENY_PATTERNS:
            if re.search(pattern, cmd_lower):
                return "Error: Command blocked by safety guard"

        if self.restrict_to_workspace:
            try:
                cwd = resolve_safe_path(str(cwd), workspace_dir)
            except PermissionError:
                return "Error: Working directory is outside workspace"

            if self._contains_outside_path(command):
                return (
                    "Error: Command blocked by workspace restriction "
                    "(outside path detected)"
                )

        try:
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(cwd),
            )
            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=self.timeout)
            except asyncio.TimeoutError:
                process.kill()
                return f"Error: Command timed out after {self.timeout}s"

            parts = []
            if stdout:
                parts.append(stdout.decode("utf-8", errors="replace"))
            if stderr:
                text = stderr.decode("utf-8", errors="replace").strip()
                if text:
                    parts.append(f"STDERR:\n{text}")
            if process.returncode != 0:
                parts.append(f"\nExit code: {process.returncode}")

            result = "\n".join(parts) if parts else "(no output)"
            if len(result) > 10000:
                result = result[:10000] + "\n... (truncated)"
            return result
        except Exception as e:
            return f"Error executing command: {e}"

    def _contains_outside_path(self, command: str) -> bool:
        # Block shell substitutions in restricted mode to reduce path obfuscation bypasses.
        if "$(" in command or "`" in command:
            return True

        try:
            tokens = shlex.split(command, posix=True)
        except ValueError:
            tokens = command.split()

        for token in tokens:
            if self._token_is_outside_path(token):
                return True
        return False

    @staticmethod
    def _token_is_outside_path(token: str) -> bool:
        if not token:
            return False

        # Ignore URLs
        low = token.lower()
        if low.startswith(("http://", "https://")):
            return False

        # Handle env assignments like PATH=/tmp/bin
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", token):
            _, token = token.split("=", 1)
            if not token:
                return False

        normalized = token.replace("\\", "/")

        # Absolute/home paths
        if normalized.startswith("/") or normalized.startswith("~/"):
            return True
        if re.match(r"^[A-Za-z]:[/\\]", token):
            return True

        # Parent traversal in any token form
        if normalized in ("..", "../"):
            return True
        if normalized.startswith("../"):
            return True
        if "/../" in normalized or normalized.endswith("/.."):
            return True

        return False
