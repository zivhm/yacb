"""WhatsApp channel using neonize (pure Python, no Node.js bridge)."""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Awaitable, Callable

from loguru import logger

from core.bus.events import OutboundMessage
from core.bus.queue import MessageBus
from core.channels.base import BaseChannel
from core.channels.commands import (
    get_commands_text,
    is_commands_request,
    is_reset_request,
    is_toggle_verbose_request,
)
from core.config import WhatsAppConfig
from core.utils.verbose import toggle_verbose

if TYPE_CHECKING:
    from core.agent.loop import AgentLoop


class WhatsAppChannel(BaseChannel):
    """WhatsApp channel using neonize (whatsmeow Go backend)."""

    name = "whatsapp"

    def __init__(self, config: WhatsAppConfig, bus: MessageBus, agent_loop: AgentLoop | None = None):
        super().__init__(config, bus)
        self.config: WhatsAppConfig = config
        self.agent_loop = agent_loop
        self._client = None
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._workspace: Path | None = None
        self._reset_callback: Callable[[str, str], Awaitable[tuple[int, int]]] | None = None

    async def start(self) -> None:
        from neonize.client import NewClient
        from neonize.events import ConnectedEv, MessageEv, PairStatusEv

        self._running = True
        self._loop = asyncio.get_running_loop()

        # Determine auth database path
        auth_dir = self.config.auth_dir
        if not auth_dir:
            auth_dir = "wa-auth"
        auth_path = Path(auth_dir)
        auth_path.mkdir(parents=True, exist_ok=True)
        db_path = str(auth_path / "neonize.db")

        logger.info(f"WhatsApp: auth database at {db_path}")

        client = NewClient(db_path)
        self._client = client

        @client.event(ConnectedEv)
        def on_connected(_: NewClient, __: ConnectedEv):
            logger.info("WhatsApp connected")

        @client.event(PairStatusEv)
        def on_pair_status(_: NewClient, ev: PairStatusEv):
            logger.info(f"WhatsApp: logged in as {ev.ID.User}")

        @client.event(MessageEv)
        def on_message(c: NewClient, ev: MessageEv):
            self._handle_neonize_message(c, ev)

        # Run neonize client in a background thread (it blocks)
        def run_client():
            try:
                client.connect()
            except Exception as e:
                if self._running:
                    logger.error(f"WhatsApp client error: {e}")

        self._thread = threading.Thread(target=run_client, daemon=True, name="whatsapp-neonize")
        self._thread.start()
        logger.info("WhatsApp channel started (neonize)")

        # Keep the coroutine alive while running
        while self._running:
            await asyncio.sleep(1)

    def _handle_neonize_message(self, client, ev) -> None:
        """Handle incoming message from neonize (called from neonize's thread)."""
        try:
            text = ""
            msg = ev.Message
            if msg.conversation:
                text = msg.conversation
            elif msg.extendedTextMessage and msg.extendedTextMessage.text:
                text = msg.extendedTextMessage.text
            elif msg.imageMessage and msg.imageMessage.caption:
                text = msg.imageMessage.caption

            if not text:
                return

            sender_jid = ev.Info.MessageSource.Sender
            chat_jid = ev.Info.MessageSource.Chat
            sender = str(sender_jid.User) if hasattr(sender_jid, 'User') else str(sender_jid)
            chat_id = str(chat_jid.User) if hasattr(chat_jid, 'User') else str(chat_jid)
            is_group = ev.Info.MessageSource.IsGroup if hasattr(ev.Info.MessageSource, 'IsGroup') else False
            push_name = ev.Info.PushName if hasattr(ev.Info, 'PushName') else ""
            normalized = text.strip().lower()

            if is_commands_request(normalized):
                if self.is_allowed(sender):
                    from neonize.utils import build_jid

                    jid = build_jid(chat_id)
                    client.send_message(jid, get_commands_text("whatsapp"))
                return

            if is_toggle_verbose_request(normalized):
                if self.is_allowed(sender):
                    from neonize.utils import build_jid

                    if not self._workspace:
                        client.send_message(build_jid(chat_id), "Workspace not configured — can't toggle verbose logs.")
                        return
                    enabled = toggle_verbose(self._workspace)
                    state = "ON" if enabled else "OFF"
                    client.send_message(build_jid(chat_id), f"Verbose logging {state}")
                return

            if is_reset_request(normalized):
                if self.is_allowed(sender):
                    from neonize.utils import build_jid

                    saved, cleared = self._reset_from_whatsapp_thread(chat_id)
                    if saved > 0:
                        text = (
                            f"Saved {saved} important note(s) to memory.\n"
                            f"Conversation history cleared ({cleared} messages)."
                        )
                    else:
                        text = f"Conversation history cleared ({cleared} messages)."
                    client.send_message(build_jid(chat_id), text)
                return

            # Schedule the async handler on the main event loop
            if self._loop and self._loop.is_running():
                asyncio.run_coroutine_threadsafe(
                    self._handle_message(
                        sender_id=sender,
                        chat_id=chat_id,
                        content=text,
                        metadata={
                            "message_id": ev.Info.ID if hasattr(ev.Info, 'ID') else "",
                            "is_group": is_group,
                            "push_name": push_name,
                        },
                    ),
                    self._loop,
                )
        except Exception as e:
            logger.error(f"WhatsApp message handling error: {e}")

    async def _reset_for_chat(self, chat_id: str) -> tuple[int, int]:
        session_key = f"{self.name}:{chat_id}"
        if self._reset_callback:
            return await self._reset_callback(self.name, chat_id)
        if self.agent_loop:
            saved = await self.agent_loop.snapshot_session_important_info(session_key)
            cleared = self.agent_loop.clear_session(session_key)
            return saved, cleared
        return 0, 0

    def _reset_from_whatsapp_thread(self, chat_id: str) -> tuple[int, int]:
        if not self._loop or not self._loop.is_running():
            return 0, 0
        try:
            future = asyncio.run_coroutine_threadsafe(self._reset_for_chat(chat_id), self._loop)
            return future.result(timeout=10)
        except Exception as e:
            logger.warning(f"WhatsApp reset command failed: {e}")
            return 0, 0

    async def stop(self) -> None:
        self._running = False
        if self._client:
            try:
                self._client.disconnect()
            except Exception:
                pass
            self._client = None
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        logger.info("WhatsApp channel stopped")

    async def send(self, msg: OutboundMessage) -> None:
        if not self._client:
            logger.warning("WhatsApp client not connected")
            return
        try:
            from neonize.utils import build_jid

            # Build JID from chat_id
            jid = build_jid(msg.chat_id)
            self._client.send_message(jid, msg.content)
        except Exception as e:
            logger.error(f"Error sending WhatsApp message: {e}")
