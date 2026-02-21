"""Base channel interface for chat platforms."""

from abc import ABC, abstractmethod
from typing import Any

from loguru import logger

from core.bus.events import InboundMessage, OutboundMessage
from core.bus.queue import MessageBus


class BaseChannel(ABC):
    """Abstract base class for chat channel implementations."""

    name: str = "base"

    def __init__(self, config: Any, bus: MessageBus):
        self.config = config
        self.bus = bus
        self._running = False

    @abstractmethod
    async def start(self) -> None:
        pass

    @abstractmethod
    async def stop(self) -> None:
        pass

    @abstractmethod
    async def send(self, msg: OutboundMessage) -> None:
        pass

    async def send_with_id(self, msg: OutboundMessage) -> str | None:
        """Send a message and return the platform message ID. Default: send normally, return None."""
        await self.send(msg)
        return None

    async def delete_message(self, chat_id: str, message_id: str) -> None:
        """Delete a message by platform ID. Default: no-op."""
        pass

    def is_allowed(self, sender_id: str) -> bool:
        allow_list = getattr(self.config, "allow_from", [])
        if not allow_list:
            return True
        sender_str = str(sender_id)
        if sender_str in allow_list:
            return True
        if "|" in sender_str:
            for part in sender_str.split("|"):
                if part and part in allow_list:
                    return True
        return False

    async def _handle_message(
        self,
        sender_id: str,
        chat_id: str,
        content: str,
        media: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if not self.is_allowed(sender_id):
            logger.warning(f"Access denied for {sender_id} on {self.name}")
            return

        msg = InboundMessage(
            channel=self.name,
            sender_id=str(sender_id),
            chat_id=str(chat_id),
            content=content,
            media=media or [],
            metadata=metadata or {},
        )
        logger.debug(f"{self.name}: publishing inbound message to bus (session={msg.session_key})")
        await self.bus.publish_inbound(msg)

    @property
    def is_running(self) -> bool:
        return self._running
