"""Discord channel using discord.py."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Awaitable, Callable

import discord
from discord import Intents, Message, app_commands
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
from core.config import DiscordConfig
from core.utils.verbose import toggle_verbose

if TYPE_CHECKING:
    from core.agent.loop import AgentLoop


class DiscordChannel(BaseChannel):
    """Discord channel using discord.py library."""

    name = "discord"

    def __init__(self, config: DiscordConfig, bus: MessageBus, agent_loop: AgentLoop | None = None):
        super().__init__(config, bus)
        self.config: DiscordConfig = config
        self.agent_loop = agent_loop
        self._client: discord.Client | None = None
        self._workspace: Path | None = None
        self._command_tree: app_commands.CommandTree | None = None
        self._commands_synced = False
        self._reset_callback: Callable[[str, str], Awaitable[tuple[int, int]]] | None = None

    async def start(self) -> None:
        if not self.config.token:
            logger.error("Discord bot token not configured")
            return

        self._running = True

        intents = Intents.default()
        intents.message_content = True
        intents.guilds = True
        intents.dm_messages = True

        self._client = discord.Client(intents=intents)
        self._command_tree = app_commands.CommandTree(self._client)

        @self._command_tree.command(name="commands", description="Show yacb command list")
        async def slash_commands(interaction: discord.Interaction):
            await interaction.response.send_message(get_commands_text("discord"), ephemeral=True)

        @self._command_tree.command(name="help", description="Show yacb command list")
        async def slash_help(interaction: discord.Interaction):
            await interaction.response.send_message(get_commands_text("discord"), ephemeral=True)

        @self._command_tree.command(name="toggle_verbose_logs", description="Toggle verbose service logs")
        async def slash_toggle_verbose(interaction: discord.Interaction):
            if not self._workspace:
                await interaction.response.send_message(
                    "Workspace not configured — can't toggle verbose logs.",
                    ephemeral=True,
                )
                return
            enabled = toggle_verbose(self._workspace)
            state = "ON" if enabled else "OFF"
            await interaction.response.send_message(f"Verbose logging **{state}**", ephemeral=True)

        @self._command_tree.command(name="reset", description="Reset chat history for this chat")
        async def slash_reset(interaction: discord.Interaction):
            saved, cleared = await self._reset_for_chat(
                chat_id=self._chat_id_for_interaction(interaction),
            )
            if saved > 0:
                text = (
                    f"Saved {saved} important note(s) to memory.\n"
                    f"Conversation history cleared ({cleared} messages)."
                )
            else:
                text = f"Conversation history cleared ({cleared} messages)."
            await interaction.response.send_message(text, ephemeral=True)

        @self._client.event
        async def on_ready():
            logger.info(f"Discord bot {self._client.user} connected")
            if self._command_tree and not self._commands_synced:
                try:
                    await self._command_tree.sync()
                    self._commands_synced = True
                    logger.info("Discord slash commands synced: /commands")
                except Exception as e:
                    logger.warning(f"Discord slash command sync failed: {e}")

        @self._client.event
        async def on_message(message: Message):
            await self._on_message(message)

        logger.info("Starting Discord bot...")
        await self._client.start(self.config.token)

    async def stop(self) -> None:
        self._running = False
        if self._client:
            logger.info("Stopping Discord bot...")
            await self._client.close()
            self._client = None

    async def send(self, msg: OutboundMessage) -> None:
        if not self._client:
            logger.debug("Discord: send() called but client is None")
            return
        logger.debug(f"Discord: sending {len(msg.content)} chars to chat_id={msg.chat_id}")
        try:
            channel = self._client.get_channel(int(msg.chat_id))
            if channel is None:
                # Try as DM user ID
                user = await self._client.fetch_user(int(msg.chat_id))
                if user:
                    channel = await user.create_dm()

            if channel and hasattr(channel, "send"):
                # Split long messages (Discord limit: 2000 chars)
                content = msg.content
                while content:
                    chunk = content[:2000]
                    content = content[2000:]
                    await channel.send(chunk)
        except Exception as e:
            logger.error(f"Error sending Discord message: {e}")

    async def _resolve_channel(self, chat_id: str):
        """Resolve a Discord channel/DM from a chat_id string."""
        channel = self._client.get_channel(int(chat_id))
        if channel is None:
            user = await self._client.fetch_user(int(chat_id))
            if user:
                channel = await user.create_dm()
        return channel

    @staticmethod
    def _chat_id_for_interaction(interaction: discord.Interaction) -> str:
        if isinstance(interaction.channel, discord.DMChannel):
            return str(interaction.user.id)
        if interaction.channel_id is not None:
            return str(interaction.channel_id)
        return str(interaction.user.id)

    async def _reset_for_chat(self, chat_id: str) -> tuple[int, int]:
        session_key = f"{self.name}:{chat_id}"
        if self._reset_callback:
            return await self._reset_callback(self.name, chat_id)
        if self.agent_loop:
            saved = await self.agent_loop.snapshot_session_important_info(session_key)
            cleared = self.agent_loop.clear_session(session_key)
            return saved, cleared
        return 0, 0

    async def send_with_id(self, msg: OutboundMessage) -> str | None:
        if not self._client:
            return None
        try:
            channel = await self._resolve_channel(msg.chat_id)
            if channel and hasattr(channel, "send"):
                sent = await channel.send(msg.content[:2000])
                return str(sent.id)
        except Exception as e:
            logger.warning(f"Discord send_with_id failed: {e}")
        return None

    async def delete_message(self, chat_id: str, message_id: str) -> None:
        if not self._client:
            return
        try:
            channel = await self._resolve_channel(chat_id)
            if channel:
                m = channel.get_partial_message(int(message_id))
                await m.delete()
        except Exception as e:
            logger.warning(f"Discord delete_message failed: {e}")

    async def _on_message(self, message: Message) -> None:
        if not self._client or message.author == self._client.user:
            return
        if message.author.bot:
            logger.debug(f"Discord: ignoring bot message from {message.author}")
            return

        sender_id = str(message.author.id)
        if message.author.name:
            sender_id = f"{sender_id}|{message.author.name}"

        # Use channel ID for groups, author ID for DMs
        if isinstance(message.channel, discord.DMChannel):
            chat_id = str(message.author.id)
        else:
            chat_id = str(message.channel.id)

        content = message.content or "[empty message]"
        normalized = content.strip().lower()

        # Handle commands
        if is_commands_request(normalized):
            try:
                await message.channel.send(get_commands_text("discord"))
            except Exception:
                pass
            return

        if is_toggle_verbose_request(normalized):
            if not self._workspace:
                return
            enabled = toggle_verbose(self._workspace)
            state = "ON" if enabled else "OFF"
            try:
                await message.channel.send(f"Verbose logging **{state}**")
            except Exception:
                pass
            return

        if is_reset_request(normalized):
            saved, cleared = await self._reset_for_chat(chat_id=chat_id)
            if saved > 0:
                text = (
                    f"Saved {saved} important note(s) to memory.\n"
                    f"Conversation history cleared ({cleared} messages)."
                )
            else:
                text = f"Conversation history cleared ({cleared} messages)."
            try:
                await message.channel.send(text)
            except Exception:
                pass
            return

        logger.debug(
            f"Discord: received message from {sender_id} in {chat_id} "
            f"(guild={message.guild}, channel_type={type(message.channel).__name__})"
        )

        # Show typing indicator (best-effort)
        try:
            await message.channel.trigger_typing()
        except Exception:
            pass

        await self._handle_message(
            sender_id=sender_id,
            chat_id=chat_id,
            content=content,
            metadata={
                "message_id": message.id,
                "guild_id": str(message.guild.id) if message.guild else None,
                "channel_name": getattr(message.channel, "name", "DM"),
                "is_dm": isinstance(message.channel, discord.DMChannel),
            },
        )
