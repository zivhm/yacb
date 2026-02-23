"""Async message queue for channel-agent communication."""

import asyncio

from loguru import logger

from core.bus.events import InboundMessage, OutboundMessage


class MessageBus:
    """Async message bus decoupling chat channels from the agent."""

    def __init__(self, inbound_maxsize: int = 200, outbound_maxsize: int = 200):
        self.inbound: asyncio.Queue[InboundMessage] = asyncio.Queue(maxsize=inbound_maxsize)
        self.outbound: asyncio.Queue[OutboundMessage] = asyncio.Queue(maxsize=outbound_maxsize)
        self._running = False

    async def publish_inbound(self, msg: InboundMessage) -> None:
        logger.debug(f"Bus <- inbound [{msg.channel}:{msg.chat_id}] from {msg.sender_id} ({len(msg.content)} chars)")
        await self.inbound.put(msg)

    async def consume_inbound(self) -> InboundMessage:
        msg = await self.inbound.get()
        logger.debug(f"Bus -> dispatch inbound [{msg.channel}:{msg.chat_id}] (queue size: {self.inbound.qsize()})")
        return msg

    async def publish_outbound(self, msg: OutboundMessage) -> None:
        logger.debug(f"Bus <- outbound [{msg.channel}:{msg.chat_id}] ({len(msg.content)} chars)")
        await self.outbound.put(msg)

    async def consume_outbound(self) -> OutboundMessage:
        msg = await self.outbound.get()
        logger.debug(f"Bus -> dispatch outbound [{msg.channel}:{msg.chat_id}] (queue size: {self.outbound.qsize()})")
        return msg

    def stop(self) -> None:
        self._running = False
