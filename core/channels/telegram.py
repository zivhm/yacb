"""Telegram channel using python-telegram-bot."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import TYPE_CHECKING, Awaitable, Callable

from loguru import logger
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from core.bus.events import OutboundMessage
from core.bus.queue import MessageBus
from core.channels.base import BaseChannel
from core.channels.commands import get_commands_text
from core.config import TelegramConfig
from core.utils.verbose import toggle_verbose

if TYPE_CHECKING:
    from core.agent.loop import AgentLoop


def _markdown_to_telegram_html(text: str) -> str:
    """Convert markdown to Telegram-safe HTML."""
    if not text:
        return ""

    # Protect code blocks
    code_blocks: list[str] = []
    def save_code_block(m: re.Match) -> str:
        code_blocks.append(m.group(1))
        return f"\x00CB{len(code_blocks) - 1}\x00"
    text = re.sub(r'```[\w]*\n?([\s\S]*?)```', save_code_block, text)

    # Protect inline code
    inline_codes: list[str] = []
    def save_inline_code(m: re.Match) -> str:
        inline_codes.append(m.group(1))
        return f"\x00IC{len(inline_codes) - 1}\x00"
    text = re.sub(r'`([^`]+)`', save_inline_code, text)

    # Headers -> plain text
    text = re.sub(r'^#{1,6}\s+(.+)$', r'\1', text, flags=re.MULTILINE)
    # Blockquotes
    text = re.sub(r'^>\s*(.*)$', r'\1', text, flags=re.MULTILINE)
    # Escape HTML
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    # Links
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2">\1</a>', text)
    # Bold
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'__(.+?)__', r'<b>\1</b>', text)
    # Italic
    text = re.sub(r'(?<![a-zA-Z0-9])_([^_]+)_(?![a-zA-Z0-9])', r'<i>\1</i>', text)
    # Strikethrough
    text = re.sub(r'~~(.+?)~~', r'<s>\1</s>', text)
    # Bullet lists
    text = re.sub(r'^[-*]\s+', '\u2022 ', text, flags=re.MULTILINE)

    # Restore inline code
    for i, code in enumerate(inline_codes):
        escaped = code.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        text = text.replace(f"\x00IC{i}\x00", f"<code>{escaped}</code>")

    # Restore code blocks
    for i, code in enumerate(code_blocks):
        escaped = code.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        text = text.replace(f"\x00CB{i}\x00", f"<pre><code>{escaped}</code></pre>")

    return text


class TelegramChannel(BaseChannel):
    """Telegram channel using long polling."""

    name = "telegram"

    def __init__(
        self,
        config: TelegramConfig,
        bus: MessageBus,
        agent_loop: AgentLoop | None = None,
    ):
        super().__init__(config, bus)
        self.config: TelegramConfig = config
        self.agent_loop = agent_loop
        self._app: Application | None = None
        self._typing_tasks: dict[str, asyncio.Task] = {}
        self._debug_chats: set[str] = set()
        self._workspace: Path | None = None
        self._reset_callback: Callable[[str, str], Awaitable[tuple[int, int]]] | None = None

    async def start(self) -> None:
        if not self.config.token:
            logger.error("Telegram bot token not configured")
            return

        self._running = True
        builder = Application.builder().token(self.config.token)
        if self.config.proxy:
            builder = builder.proxy(self.config.proxy).get_updates_proxy(self.config.proxy)
        self._app = builder.build()

        self._app.add_handler(CommandHandler("start", self._on_start))
        self._app.add_handler(CommandHandler("reset", self._on_reset))
        self._app.add_handler(CommandHandler("debug", self._on_debug))
        self._app.add_handler(CommandHandler("toggle_verbose_logs", self._on_toggle_verbose))
        self._app.add_handler(CommandHandler("commands", self._on_help))
        self._app.add_handler(CommandHandler("help", self._on_help))
        self._app.add_handler(
            MessageHandler(
                (filters.TEXT | filters.PHOTO | filters.Document.ALL) & ~filters.COMMAND,
                self._on_message,
            )
        )

        logger.info("Starting Telegram bot (polling)...")
        await self._app.initialize()
        await self._app.start()

        bot_info = await self._app.bot.get_me()
        logger.info(f"Telegram bot @{bot_info.username} connected")

        await self._app.updater.start_polling(
            allowed_updates=["message"],
            drop_pending_updates=True,
        )

        while self._running:
            await asyncio.sleep(1)

    async def stop(self) -> None:
        self._running = False
        for chat_id in list(self._typing_tasks):
            self._stop_typing(chat_id)
        if self._app:
            logger.info("Stopping Telegram bot...")
            await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()
            self._app = None

    async def send(self, msg: OutboundMessage) -> None:
        if not self._app:
            logger.debug("Telegram: send() called but app is None")
            return
        logger.debug(f"Telegram: sending {len(msg.content)} chars to chat_id={msg.chat_id}")
        self._stop_typing(msg.chat_id)
        try:
            chat_id = int(msg.chat_id)
            content = msg.content
            if msg.chat_id in self._debug_chats and msg.metadata.get("model"):
                tier = msg.metadata.get("tier", "?")
                model = msg.metadata["model"]
                content += f"\n\n🔧 {tier} → {model}"
            html_content = _markdown_to_telegram_html(content)
            await self._app.bot.send_message(chat_id=chat_id, text=html_content, parse_mode="HTML")
        except Exception as e:
            logger.warning(f"HTML parse failed, falling back to plain text: {e}")
            try:
                await self._app.bot.send_message(chat_id=int(msg.chat_id), text=msg.content)
            except Exception as e2:
                logger.error(f"Error sending Telegram message: {e2}")

    async def send_with_id(self, msg: OutboundMessage) -> str | None:
        if not self._app:
            return None
        self._stop_typing(msg.chat_id)
        try:
            chat_id = int(msg.chat_id)
            html_content = _markdown_to_telegram_html(msg.content)
            sent = await self._app.bot.send_message(
                chat_id=chat_id, text=html_content, parse_mode="HTML",
            )
            return str(sent.message_id)
        except Exception as e:
            logger.warning(f"Telegram send_with_id failed: {e}")
            return None

    async def delete_message(self, chat_id: str, message_id: str) -> None:
        if not self._app:
            return
        try:
            await self._app.bot.delete_message(
                chat_id=int(chat_id), message_id=int(message_id),
            )
        except Exception as e:
            logger.warning(f"Telegram delete_message failed: {e}")

    async def _on_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message or not update.effective_user:
            return
        user = update.effective_user
        await update.message.reply_text(
            f"Hi {user.first_name}! I'm yacb.\nSend me a message and I'll respond.\nType /commands for available commands."
        )

    async def _on_reset(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message or not update.effective_user:
            return
        chat_id = str(update.message.chat_id)
        session_key = f"{self.name}:{chat_id}"
        saved = 0
        cleared = 0
        if self._reset_callback:
            saved, cleared = await self._reset_callback(self.name, chat_id)
        elif self.agent_loop:
            saved = await self.agent_loop.snapshot_session_important_info(session_key)
            cleared = self.agent_loop.clear_session(session_key)
        logger.info(
            f"Session reset for {session_key} (saved {saved} important items, cleared {cleared} messages)"
        )
        if saved > 0:
            await update.message.reply_text(
                f"Saved {saved} important note(s) to memory.\nConversation history cleared."
            )
        else:
            await update.message.reply_text("Conversation history cleared.")

    async def _on_debug(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message:
            return
        chat_id = str(update.message.chat_id)
        if chat_id in self._debug_chats:
            self._debug_chats.discard(chat_id)
            await update.message.reply_text("Debug mode OFF")
            logger.info(f"Debug mode disabled for chat {chat_id}")
        else:
            self._debug_chats.add(chat_id)
            await update.message.reply_text("Debug mode ON — I'll show the model used per message.")
            logger.info(f"Debug mode enabled for chat {chat_id}")

    async def _on_toggle_verbose(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message:
            return
        if self._workspace:
            enabled = toggle_verbose(self._workspace)
            state = "ON" if enabled else "OFF"
            await update.message.reply_text(f"Verbose logging {state}")
        else:
            await update.message.reply_text("Workspace not configured — can't toggle verbose logs.")

    async def _on_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message:
            return
        await update.message.reply_text(get_commands_text("telegram"))

    async def _on_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message or not update.effective_user:
            logger.debug(f"Telegram: skipping update (message={update.message is not None}, user={update.effective_user is not None})")
            return

        message = update.message
        user = update.effective_user
        chat_id = message.chat_id

        sender_id = str(user.id)
        if user.username:
            sender_id = f"{sender_id}|{user.username}"

        content_parts = []
        if message.text:
            content_parts.append(message.text)
        if message.caption:
            content_parts.append(message.caption)

        content = "\n".join(content_parts) if content_parts else "[empty message]"

        logger.debug(
            f"Telegram: received from {sender_id} in chat {chat_id} "
            f"(type={message.chat.type}, has_text={bool(message.text)}, has_photo={bool(message.photo)})"
        )

        str_chat_id = str(chat_id)
        self._start_typing(str_chat_id)

        await self._handle_message(
            sender_id=sender_id,
            chat_id=str_chat_id,
            content=content,
            metadata={
                "message_id": message.message_id,
                "user_id": user.id,
                "username": user.username,
                "first_name": user.first_name,
                "is_group": message.chat.type != "private",
            },
        )

    def _start_typing(self, chat_id: str) -> None:
        self._stop_typing(chat_id)
        self._typing_tasks[chat_id] = asyncio.create_task(self._typing_loop(chat_id))

    def _stop_typing(self, chat_id: str) -> None:
        task = self._typing_tasks.pop(chat_id, None)
        if task and not task.done():
            task.cancel()

    async def _typing_loop(self, chat_id: str) -> None:
        try:
            while self._app:
                await self._app.bot.send_chat_action(chat_id=int(chat_id), action="typing")
                await asyncio.sleep(4)
        except asyncio.CancelledError:
            pass
        except Exception:
            pass
