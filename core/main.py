"""yacb - Entry point. Starts all services."""

import asyncio
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from core.bus.events import OutboundMessage
from core.utils.logger import setup_logging
from core.utils.verbose import load_verbose_state

if TYPE_CHECKING:
    from core.agent.loop import AgentLoop


class Clvd:
    """Main application: wires bus, router, channels, cron, heartbeat."""

    def __init__(self, config_path: str = "config.yaml"):
        from core.agent.router import AgentRouter
        from core.bus.queue import MessageBus
        from core.config import load_config

        self.config = load_config(config_path)
        self.bus = MessageBus()
        self.router = AgentRouter(self.config, self.bus)
        self._channels: dict[str, Any] = {}
        self._tasks: list[asyncio.Task] = []
        self._heartbeats: dict[str, Any] = {}
        # Track thinking messages:
        # "channel:chat_id:turn_id" (or legacy "channel:chat_id") -> (channel_name, platform_msg_id)
        self._thinking_messages: dict[str, tuple[str, str]] = {}
        self._restart_requested = False
        self._update_requested = False

    async def start(self) -> None:
        logger.info("yacb starting...")

        # Load verbose logging state from workspace
        workspace = self.config.workspace_path()
        verbose = load_verbose_state(workspace)
        if verbose:
            logger.info("Verbose logging is ON (persisted from last session)")

        # Start channels (pass workspace for verbose toggle command)
        self._init_channels(workspace)

        # Eagerly start cron services for all configured agents
        # This ensures reminders survive bot restarts
        await self._init_cron_services()

        # Start inbound dispatcher (routes messages to correct agent)
        self._tasks.append(asyncio.create_task(self._dispatch_inbound()))

        # Start outbound dispatcher (routes responses to correct channel)
        self._tasks.append(asyncio.create_task(self._dispatch_outbound()))

        # Start channels
        for name, channel in self._channels.items():
            logger.info(f"Starting {name} channel...")
            self._tasks.append(asyncio.create_task(self._start_channel(name, channel)))

        # Start heartbeat for agents that have it enabled
        for agent_name in self.config.agents:
            agent = self.router.get_or_create_agent(agent_name)
            if agent.agent_config.heartbeat.enabled:
                await self._start_heartbeat(agent_name, agent)

        if self.config.tools.security_audit.enabled:
            self._tasks.append(asyncio.create_task(self._periodic_security_audit()))

        logger.info(f"yacb running with {len(self._channels)} channel(s)")

        # Wait for all tasks
        try:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        except asyncio.CancelledError:
            pass

    async def stop(self) -> None:
        logger.info("yacb stopping...")
        for task in self._tasks:
            task.cancel()
        for name, channel in self._channels.items():
            try:
                await channel.stop()
            except Exception as e:
                logger.error(f"Error stopping {name}: {e}")
        for agent_name, hb in list(self._heartbeats.items()):
            try:
                hb.stop()
            except Exception as e:
                logger.error(f"Error stopping heartbeat for {agent_name}: {e}")
        self._heartbeats.clear()
        self.bus.stop()
        logger.info("yacb stopped")

    async def _init_cron_services(self) -> None:
        """Start cron services for all configured agents eagerly."""
        for agent_name in self.config.agents:
            agent = self.router.get_or_create_agent(agent_name)
            if agent.cron_service and not agent.cron_service._running:
                await self._wire_and_start_cron(agent)
                logger.info(f"Cron service started eagerly for agent '{agent_name}'")

    async def _periodic_security_audit(self) -> None:
        interval_minutes = self.config.tools.security_audit.interval_minutes
        interval_seconds = max(60, interval_minutes * 60)
        logger.info(f"Periodic security audit enabled (every {interval_minutes}m)")

        while True:
            try:
                findings = _collect_periodic_audit_findings(self.config)
                summary = _summarize_audit_levels(findings)
                summary_line = (
                    "Periodic security audit summary: "
                    f"PASS={summary['PASS']} WARN={summary['WARN']} FAIL={summary['FAIL']}"
                )
                if summary["FAIL"] > 0:
                    logger.error(summary_line)
                elif summary["WARN"] > 0:
                    logger.warning(summary_line)
                else:
                    logger.info(summary_line)

                for finding in findings:
                    if finding["level"] == "PASS":
                        continue
                    line = f"[audit:{finding['check']}] {finding['message']}"
                    if finding["level"] == "FAIL":
                        logger.error(line)
                    else:
                        logger.warning(line)

                await asyncio.sleep(interval_seconds)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(f"Periodic security audit failed: {e}")
                await asyncio.sleep(interval_seconds)

    def _init_channels(self, workspace: Path) -> None:
        if self.config.channels.telegram.enabled:
            try:
                from core.channels.telegram import TelegramChannel
                ch = TelegramChannel(self.config.channels.telegram, self.bus)
                ch._workspace = workspace
                ch._reset_callback = self._reset_session
                self._channels["telegram"] = ch
                logger.info("Telegram channel enabled")
            except ImportError as e:
                logger.warning(f"Telegram not available: {e}")

        if self.config.channels.whatsapp.enabled:
            try:
                from core.channels.whatsapp import WhatsAppChannel
                ch = WhatsAppChannel(self.config.channels.whatsapp, self.bus)
                ch._workspace = workspace
                ch._reset_callback = self._reset_session
                self._channels["whatsapp"] = ch
                logger.info("WhatsApp channel enabled")
            except ImportError as e:
                logger.warning(f"WhatsApp not available: {e}")

        if self.config.channels.discord.enabled:
            try:
                from core.channels.discord import DiscordChannel
                ch = DiscordChannel(self.config.channels.discord, self.bus)
                ch._workspace = workspace
                ch._reset_callback = self._reset_session
                self._channels["discord"] = ch
                logger.info("Discord channel enabled")
            except ImportError as e:
                logger.warning(f"Discord not available: {e}")

    async def _reset_session(self, channel: str, chat_id: str) -> tuple[int, int]:
        """Persist important session context, then clear in-memory chat history."""
        agent_name = self.router.resolve(channel, chat_id)
        agent = self.router.get_or_create_agent(agent_name)
        session_key = f"{channel}:{chat_id}"

        saved = await agent.snapshot_session_important_info(session_key)
        cleared = agent.clear_session(session_key)
        return saved, cleared

    async def _start_channel(self, name: str, channel) -> None:
        try:
            await channel.start()
        except Exception as e:
            logger.error(f"Failed to start {name}: {e}")

    async def _dispatch_inbound(self) -> None:
        """Route inbound messages to the correct agent."""
        logger.info("Inbound dispatcher started")
        while True:
            try:
                msg = await self.bus.consume_inbound()

                # Resolve agent
                agent_name = self.router.resolve(msg.channel, msg.chat_id)
                logger.debug(f"Dispatch: [{msg.channel}:{msg.chat_id}] -> agent '{agent_name}'")
                agent = self.router.get_or_create_agent(agent_name)

                # Start cron service if not yet running
                if agent.cron_service and not agent.cron_service._running:
                    await self._wire_and_start_cron(agent)

                # Process through agent
                try:
                    response = await agent._process_message(msg)
                    if response:
                        logger.debug(f"Dispatch: agent responded ({len(response.content)} chars) -> outbound")
                        await self.bus.publish_outbound(response)
                except Exception as e:
                    logger.error(f"Agent error: {e}")
                    await self.bus.publish_outbound(OutboundMessage(
                        channel=msg.channel, chat_id=msg.chat_id,
                        content=f"Sorry, I encountered an error: {e}",
                        metadata={"clear_thinking": True},
                    ))
            except asyncio.CancelledError:
                break

    async def _dispatch_outbound(self) -> None:
        """Route outbound messages to the correct channel."""
        logger.info("Outbound dispatcher started")
        while True:
            try:
                msg = await self.bus.consume_outbound()
                channel = self._channels.get(msg.channel)
                if not channel:
                    logger.warning(f"Unknown channel: {msg.channel}")
                    continue

                try:
                    if msg.metadata.get("thinking"):
                        # Send thinking indicator and track its platform message ID
                        platform_id = await channel.send_with_id(msg)
                        thinking_key = self._thinking_key(msg.channel, msg.chat_id, msg.metadata)
                        if platform_id:
                            self._thinking_messages[thinking_key] = (msg.channel, platform_id)
                        logger.debug(f"Thinking message sent: {thinking_key} -> {platform_id}")
                        continue

                    if msg.metadata.get("clear_thinking"):
                        await self._clear_thinking_messages(channel, msg)

                    await channel.send(msg)

                    if msg.metadata.get("restart_requested"):
                        await self._request_restart()
                    if msg.metadata.get("update_requested"):
                        await self._request_update(msg.channel, msg.chat_id)
                except Exception as e:
                    logger.error(f"Error sending to {msg.channel}: {e}")
            except asyncio.CancelledError:
                break

    async def _request_restart(self) -> None:
        """Schedule a process restart after sending confirmation to chat."""
        if self._restart_requested:
            return
        self._restart_requested = True
        logger.warning("Restart requested from chat command; scheduling process re-exec")
        self._tasks.append(asyncio.create_task(self._restart_process()))

    async def _restart_process(self) -> None:
        """Re-exec the current runtime process in foreground mode."""
        await asyncio.sleep(0.8)
        config_path = os.environ.get("YACB_CONFIG_PATH", "config.yaml")
        restart_cmd = [sys.executable, "-m", "core.main", "run", config_path]

        # Best effort channel shutdown before replacing the process image.
        for name, channel in self._channels.items():
            try:
                await asyncio.wait_for(channel.stop(), timeout=2.0)
            except Exception as e:
                logger.warning(f"Restart: failed to stop {name} cleanly: {e}")

        logger.warning(f"Restarting process via exec: {restart_cmd}")
        os.execv(sys.executable, restart_cmd)

    async def _request_update(self, channel_name: str, chat_id: str) -> None:
        """Schedule a git update + restart flow."""
        if self._update_requested:
            return
        self._update_requested = True
        logger.warning("Update requested from chat command; scheduling git pull flow")
        self._tasks.append(asyncio.create_task(self._update_and_restart(channel_name, chat_id)))

    async def _update_and_restart(self, channel_name: str, chat_id: str) -> None:
        """Run git pull --ff-only and request restart on success."""
        project_root = Path(__file__).resolve().parent.parent
        cmd = ["git", "-C", str(project_root), "pull", "--ff-only"]
        logger.warning(f"Running update command: {' '.join(cmd)}")

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
        except Exception as e:
            self._update_requested = False
            await self.bus.publish_outbound(
                OutboundMessage(
                    channel=channel_name,
                    chat_id=chat_id,
                    content=f"Update failed to start: {e}",
                    metadata={"model": "system/control", "tier": "medium"},
                )
            )
            return

        out_text = (stdout or b"").decode("utf-8", errors="replace").strip()
        err_text = (stderr or b"").decode("utf-8", errors="replace").strip()

        if proc.returncode != 0:
            self._update_requested = False
            details = err_text or out_text or "unknown git error"
            details = details.splitlines()[-1] if details else "unknown git error"
            await self.bus.publish_outbound(
                OutboundMessage(
                    channel=channel_name,
                    chat_id=chat_id,
                    content=f"Update failed: {details}",
                    metadata={"model": "system/control", "tier": "medium"},
                )
            )
            return

        summary = out_text or "Already up to date."
        summary_line = summary.splitlines()[-1] if summary else "Already up to date."
        await self.bus.publish_outbound(
            OutboundMessage(
                channel=channel_name,
                chat_id=chat_id,
                content=f"Update complete: {summary_line}\nRestarting yacb now...",
                metadata={
                    "model": "system/control",
                    "tier": "medium",
                    "restart_requested": True,
                },
            )
        )

    async def _start_heartbeat(self, agent_name: str, agent: "AgentLoop") -> None:
        from core.cron.heartbeat import HeartbeatService

        existing = self._heartbeats.get(agent_name)
        if existing:
            existing.stop()

        hb_config = agent.agent_config.heartbeat

        async def on_heartbeat(prompt: str) -> str:
            return await agent.process_direct(prompt)

        # Parse deliver_to into channel + chat_id for delivery callback
        on_deliver = None
        if hb_config.deliver_to and ":" in hb_config.deliver_to:
            channel, chat_id = hb_config.deliver_to.split(":", 1)

            async def on_deliver(response: str) -> None:
                await self.bus.publish_outbound(OutboundMessage(
                    channel=channel,
                    chat_id=chat_id,
                    content=response,
                ))

        hb = HeartbeatService(
            workspace=agent.workspace,
            interval_minutes=hb_config.interval_minutes,
            on_heartbeat=on_heartbeat,
            on_deliver=on_deliver,
            active_hours_start=hb_config.active_hours_start,
            active_hours_end=hb_config.active_hours_end,
            suppress_empty=hb_config.suppress_empty,
        )
        await hb.start()
        self._heartbeats[agent_name] = hb
        logger.info(f"Heartbeat started for agent '{agent_name}'")

    async def _wire_and_start_cron(self, agent: "AgentLoop") -> None:
        """Wire on_job callback and start cron service for an agent."""
        async def on_job(job, _agent=agent):
            if not job.payload.deliver or not job.payload.channel or not job.payload.to:
                logger.warning(f"Cron delivery: '{job.name}' has no delivery target (deliver={job.payload.deliver}, channel={job.payload.channel}, to={job.payload.to})")
                return

            if job.payload.direct_delivery:
                # Direct mode: skip LLM, send message straight to user
                logger.info(f"Cron direct delivery: '{job.name}' -> {job.payload.channel}:{job.payload.to}")
                await self.bus.publish_outbound(OutboundMessage(
                    channel=job.payload.channel,
                    chat_id=job.payload.to,
                    content=job.payload.message,
                ))
            else:
                # Agent mode: process through LLM first
                logger.info(f"Cron delivery: processing '{job.name}' through agent")
                response = await _agent.process_direct(job.payload.message)
                logger.info(f"Cron delivery: sending to {job.payload.channel}:{job.payload.to}")
                await self.bus.publish_outbound(OutboundMessage(
                    channel=job.payload.channel,
                    chat_id=job.payload.to,
                    content=response,
                ))
            logger.info(f"Cron delivery: '{job.name}' sent successfully")

        agent.cron_service.on_job = on_job
        await agent.cron_service.start()
        logger.info("Cron service wired and started for agent")

    @staticmethod
    def _thinking_key(channel: str, chat_id: str, metadata: dict[str, Any]) -> str:
        turn_id = str(metadata.get("turn_id", "")).strip()
        if turn_id:
            return f"{channel}:{chat_id}:{turn_id}"
        return f"{channel}:{chat_id}"

    async def _clear_thinking_messages(self, channel: Any, msg: OutboundMessage) -> None:
        """Clear one thinking message (turn-specific) or all for chat (fallback)."""
        turn_id = str(msg.metadata.get("turn_id", "")).strip()
        if turn_id:
            keys = [f"{msg.channel}:{msg.chat_id}:{turn_id}"]
        else:
            prefix = f"{msg.channel}:{msg.chat_id}"
            keys = [
                key for key in list(self._thinking_messages.keys())
                if key == prefix or key.startswith(prefix + ":")
            ]

        for key in keys:
            stored = self._thinking_messages.pop(key, None)
            if not stored:
                continue
            _, platform_id = stored
            await channel.delete_message(msg.chat_id, platform_id)
            logger.debug(f"Thinking message cleared: {key}")


def _parse_setup_args(args: list[str], default_config: str) -> tuple[str, bool]:
    """Parse setup CLI args: [config_path] [--tui|--app]."""
    flags = {"--tui", "--app"}
    tui = any(arg in flags for arg in args)
    positional = [arg for arg in args if arg not in flags]
    config_path = positional[0] if positional else default_config
    return config_path, tui


def _parse_service_args(args: list[str], default_config: str) -> tuple[str, str, bool]:
    """Parse service args: <action> [config_path] [--follow|-f]."""
    if not args:
        return "", default_config, False

    action = args[0].strip().lower()
    follow = False
    positional: list[str] = []
    for arg in args[1:]:
        if arg in {"--follow", "-f"}:
            follow = True
        else:
            positional.append(arg)
    config_path = positional[0] if positional else default_config
    return action, config_path, follow


def _service_paths(project_root: Path) -> tuple[Path, Path]:
    primary = (project_root / ".yacb").resolve()
    if _can_prepare_runtime_dir(primary):
        return primary / "service.pid", primary / "service.log"

    fallback = (Path.home() / ".yacb" / "service").expanduser().resolve()
    if _can_prepare_runtime_dir(fallback):
        return fallback / "service.pid", fallback / "service.log"

    raise PermissionError(
        f"Could not prepare writable service directory at '{primary}' or '{fallback}'."
    )


def _can_prepare_runtime_dir(path: Path) -> bool:
    """Return whether runtime can create/write in a service directory."""
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except Exception:
        return False


def _service_child_cmd(resolved_config: str) -> list[str]:
    """Foreground child command used by background service start."""
    return [sys.executable, "-m", "core.main", "run", resolved_config]


def _read_pid(pid_path: Path) -> int | None:
    if not pid_path.exists():
        return None
    value = pid_path.read_text(encoding="utf-8").strip()
    if not value:
        return None
    try:
        pid = int(value)
    except ValueError:
        return None
    return pid if pid > 0 else None


def _is_pid_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _stop_pid(pid: int, timeout_seconds: float = 8.0) -> bool:
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return False

    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if not _is_pid_running(pid):
            return True
        time.sleep(0.2)

    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        return False
    return not _is_pid_running(pid)


def _read_last_log_lines(log_path: Path, limit: int = 80) -> list[str]:
    if not log_path.exists():
        return []
    lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    if len(lines) <= limit:
        return lines
    return lines[-limit:]


def _print_service_usage() -> None:
    print("Usage:")
    print("  yacb <start|stop|status|logs> [config_path] [--follow]")
    print("  yacb service <start|stop|status|logs> [config_path] [--follow]")
    print("Examples:")
    print("  yacb start")
    print("  yacb start config.local.yaml")
    print("  yacb status")
    print("  yacb logs -f")
    print("  yacb stop")
    print("  yacb run            # foreground mode")
    print("  yacb init           # setup wizard alias")


def _print_main_usage() -> None:
    print("yacb commands:")
    print("  yacb                     # start background service")
    print("  yacb start [config]      # start background service")
    print("  yacb status              # service status")
    print("  yacb logs [-f]           # service logs")
    print("  yacb stop                # stop service")
    print("  yacb run [config]        # run foreground")
    print("  yacb init                # setup wizard")
    print("  yacb config <channel>    # configure one channel")


def _collect_periodic_audit_findings(config: Any) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []

    provider_data = config.providers.model_dump()
    configured_providers = sorted(
        name for name, data in provider_data.items() if (data or {}).get("api_key")
    )
    if configured_providers:
        findings.append({
            "level": "PASS",
            "check": "providers",
            "message": (
                f"{len(configured_providers)} provider key(s) configured: "
                f"{', '.join(configured_providers)}"
            ),
        })
    else:
        findings.append({
            "level": "FAIL",
            "check": "providers",
            "message": "No provider API keys configured.",
        })

    channel_data = config.channels.model_dump()
    enabled_channels = sorted(
        name for name, data in channel_data.items() if data.get("enabled")
    )
    if not enabled_channels:
        findings.append({
            "level": "WARN",
            "check": "channels",
            "message": "No channels enabled.",
        })
    else:
        findings.append({
            "level": "PASS",
            "check": "channels",
            "message": f"Enabled channels: {', '.join(enabled_channels)}",
        })
        for name in enabled_channels:
            allow_from = channel_data.get(name, {}).get("allow_from", [])
            if allow_from:
                findings.append({
                    "level": "PASS",
                    "check": f"allow_from:{name}",
                    "message": f"{name} access list has {len(allow_from)} entry(ies).",
                })
            else:
                findings.append({
                    "level": "WARN",
                    "check": f"allow_from:{name}",
                    "message": f"{name} is enabled with open access (allow_from is empty).",
                })

    if config.tools.restrict_to_workspace:
        findings.append({
            "level": "PASS",
            "check": "workspace_lock",
            "message": "tools.restrict_to_workspace is enabled.",
        })
    else:
        findings.append({
            "level": "WARN",
            "check": "workspace_lock",
            "message": "tools.restrict_to_workspace is disabled.",
        })

    shell_agents = sorted(
        name for name, agent in config.agents.items() if "shell" in (agent.tools or [])
    )
    if shell_agents and not config.tools.restrict_to_workspace:
        findings.append({
            "level": "WARN",
            "check": "shell_exposure",
            "message": (
                "Shell-enabled agents are running without workspace restriction: "
                f"{', '.join(shell_agents)}"
            ),
        })
    elif shell_agents:
        findings.append({
            "level": "PASS",
            "check": "shell_exposure",
            "message": f"Shell-enabled agents: {', '.join(shell_agents)}",
        })

    heartbeat_warned = False
    for name, agent in config.agents.items():
        if agent.heartbeat.enabled and not agent.heartbeat.deliver_to:
            heartbeat_warned = True
            findings.append({
                "level": "WARN",
                "check": f"heartbeat:{name}",
                "message": "Heartbeat is enabled but deliver_to is empty.",
            })
    if not heartbeat_warned:
        findings.append({
            "level": "PASS",
            "check": "heartbeat",
            "message": "No heartbeat delivery misconfiguration detected.",
        })

    return findings


def _summarize_audit_levels(findings: list[dict[str, str]]) -> dict[str, int]:
    return {
        "PASS": sum(1 for finding in findings if finding["level"] == "PASS"),
        "WARN": sum(1 for finding in findings if finding["level"] == "WARN"),
        "FAIL": sum(1 for finding in findings if finding["level"] == "FAIL"),
    }


def _run_service_command(args: list[str], default_config: str, project_root: Path) -> int:
    action, config_path, follow = _parse_service_args(args, default_config)
    try:
        pid_path, log_path = _service_paths(project_root)
    except PermissionError as e:
        print(f"Error: {e}")
        return 1

    if action not in {"start", "stop", "status", "logs"}:
        _print_service_usage()
        return 1

    pid_path.parent.mkdir(parents=True, exist_ok=True)
    existing_pid = _read_pid(pid_path)

    if action == "start":
        if existing_pid and _is_pid_running(existing_pid):
            print(f"yacb service is already running (PID {existing_pid})")
            print(f"Log file: {log_path}")
            return 0

        if pid_path.exists():
            pid_path.unlink(missing_ok=True)

        resolved_config = str(Path(config_path).expanduser().resolve())
        # Use explicit foreground mode in the child process to avoid CLI recursion.
        cmd = _service_child_cmd(resolved_config)

        with log_path.open("a", encoding="utf-8") as log_file:
            kwargs = {
                "stdin": subprocess.DEVNULL,
                "stdout": log_file,
                "stderr": subprocess.STDOUT,
                "cwd": str(project_root),
                "close_fds": True,
            }
            if sys.platform == "win32":
                flags = (
                    getattr(subprocess, "DETACHED_PROCESS", 0)
                    | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                )
                process = subprocess.Popen(cmd, creationflags=flags, **kwargs)
            else:
                process = subprocess.Popen(cmd, start_new_session=True, **kwargs)

        pid_path.write_text(str(process.pid), encoding="utf-8")
        time.sleep(0.4)
        if process.poll() is not None:
            pid_path.unlink(missing_ok=True)
            print("yacb service failed to start (process exited immediately).")
            print(f"Check logs: {log_path}")
            return 1

        print(f"yacb service started (PID {process.pid})")
        print(f"Config: {resolved_config}")
        print(f"Logs: {log_path}")
        return 0

    if action == "stop":
        if not existing_pid:
            print("yacb service is not running (no PID file).")
            return 0
        if not _is_pid_running(existing_pid):
            pid_path.unlink(missing_ok=True)
            print(f"Removed stale PID file ({existing_pid}).")
            return 0
        stopped = _stop_pid(existing_pid)
        if stopped:
            pid_path.unlink(missing_ok=True)
            print(f"yacb service stopped (PID {existing_pid}).")
            return 0
        print(f"Failed to stop yacb service (PID {existing_pid}).")
        return 1

    if action == "status":
        if existing_pid and _is_pid_running(existing_pid):
            print(f"yacb service is running (PID {existing_pid})")
            print(f"Logs: {log_path}")
            return 0
        if existing_pid and not _is_pid_running(existing_pid):
            pid_path.unlink(missing_ok=True)
            print("yacb service is not running (stale PID file was removed).")
            return 1
        print("yacb service is not running.")
        return 1

    print(f"Log file: {log_path}")
    if not log_path.exists():
        print("No logs yet.")
        return 0

    for line in _read_last_log_lines(log_path):
        print(line)
    if follow:
        try:
            with log_path.open("r", encoding="utf-8", errors="replace") as f:
                f.seek(0, os.SEEK_END)
                while True:
                    line = f.readline()
                    if line:
                        print(line.rstrip())
                    else:
                        time.sleep(0.2)
        except KeyboardInterrupt:
            return 0
    return 0


def main():
    """CLI entry point."""
    project_root = Path(__file__).resolve().parent.parent
    setup_default_config = str(project_root / "config.local.yaml")
    runtime_default_config = setup_default_config
    if not Path(runtime_default_config).exists():
        runtime_default_config = str(project_root / "config.yaml")

    args = sys.argv[1:]

    if args and args[0] in {"-h", "--help", "help"}:
        _print_main_usage()
        return

    # Handle setup/init
    if args and args[0] in {"setup", "init"}:
        from core.setup import run_setup
        config_path, tui = _parse_setup_args(args[1:], setup_default_config)
        run_setup(config_path, tui=tui)
        return

    if args and args[0] == "config":
        from core.setup import run_channel_config
        channel_name = args[1] if len(args) > 1 else None
        if not channel_name:
            print("Usage: yacb config <channel>")
            print("Channels: telegram, whatsapp, discord")
            return
        config_path = args[2] if len(args) > 2 else setup_default_config
        run_channel_config(channel_name, config_path)
        return

    # Legacy namespace: yacb service <action> ...
    if args and args[0] == "service":
        raise SystemExit(_run_service_command(args[1:], runtime_default_config, project_root))

    # New short service commands: yacb start|stop|status|logs ...
    if args and args[0] in {"start", "stop", "status", "logs"}:
        raise SystemExit(_run_service_command(args, runtime_default_config, project_root))

    # Background-by-default for bare "yacb"
    if not args:
        raise SystemExit(_run_service_command(["start"], runtime_default_config, project_root))

    # Backward-compatible shorthand: "yacb <config_path>" starts service with that config.
    if args[0] not in {"run", "foreground", "fg"}:
        raise SystemExit(_run_service_command(["start", *args], runtime_default_config, project_root))

    setup_logging()

    # Foreground mode only (explicit): yacb run [config_path]
    config_path = args[1] if len(args) > 1 else runtime_default_config
    os.environ["YACB_CONFIG_PATH"] = str(Path(config_path).expanduser().resolve())

    app = Clvd(config_path)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def shutdown():
        logger.info("Shutdown signal received")
        loop.create_task(app.stop())

    # Handle signals
    if sys.platform != "win32":
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, shutdown)

    try:
        loop.run_until_complete(app.start())
    except KeyboardInterrupt:
        logger.info("Interrupted")
        loop.run_until_complete(app.stop())
    finally:
        loop.close()


if __name__ == "__main__":
    main()
