"""Message tool for sending messages to users."""

from typing import Any, Awaitable, Callable

from core.bus.events import OutboundMessage
from core.tools.base import Tool


class MessageTool(Tool):
    """Send messages to users on chat channels."""

    def __init__(self, send_callback: Callable[[OutboundMessage], Awaitable[None]] | None = None):
        self._send_callback = send_callback
        self._channel = ""
        self._chat_id = ""

    def set_context(self, channel: str, chat_id: str) -> None:
        self._channel = channel
        self._chat_id = chat_id

    @property
    def name(self) -> str:
        return "message"

    @property
    def description(self) -> str:
        return "Send a message to the user on a chat channel."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "The message content"},
                "channel": {"type": "string", "description": "Target channel (optional)"},
                "chat_id": {"type": "string", "description": "Target chat ID (optional)"},
            },
            "required": ["content"],
        }

    async def execute(self, content: str, channel: str | None = None, chat_id: str | None = None, **kwargs: Any) -> str:
        channel = channel or self._channel
        chat_id = chat_id or self._chat_id

        if not channel or not chat_id:
            return "Error: No target channel/chat specified"
        if not self._send_callback:
            return "Error: Message sending not configured"

        msg = OutboundMessage(channel=channel, chat_id=chat_id, content=content)
        try:
            await self._send_callback(msg)
            return f"Message sent to {channel}:{chat_id}"
        except Exception as e:
            return f"Error sending message: {e}"
