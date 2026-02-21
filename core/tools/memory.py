"""Memory tool for the 3-layer knowledge base."""

from typing import Any

from core.agent.memory import MemoryStore
from core.tools.base import Tool


class MemoryTool(Tool):
    """Store, recall, and organize knowledge in the memory hierarchy."""

    def __init__(self, memory_store: MemoryStore):
        self._mem = memory_store

    @property
    def name(self) -> str:
        return "memory"

    @property
    def description(self) -> str:
        return (
            "Manage the knowledge base. Actions: "
            "remember (store a fact), recall (search facts), "
            "categories (list topic groups), forget (remove a fact)."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["remember", "recall", "categories", "forget"],
                    "description": "Action to perform",
                },
                "content": {
                    "type": "string",
                    "description": "Fact to store (remember) or search query (recall)",
                },
                "category": {
                    "type": "string",
                    "description": "Topic category (for remember). Auto-assigned if omitted.",
                },
                "item_id": {
                    "type": "integer",
                    "description": "Item ID (for forget)",
                },
            },
            "required": ["action"],
        }

    async def execute(
        self, action: str, content: str = "", category: str = "uncategorized",
        item_id: int | None = None, **kwargs: Any,
    ) -> str:
        if action == "remember":
            return await self._remember(content, category)
        elif action == "recall":
            return await self._recall(content)
        elif action == "categories":
            return await self._categories()
        elif action == "forget":
            return await self._forget(item_id)
        return f"Unknown action: {action}"

    async def _remember(self, content: str, category: str) -> str:
        if not content:
            return "Error: content is required"
        item_id = await self._mem.remember(content, category)
        return f"Stored as item #{item_id} in [{category}]"

    async def _recall(self, query: str) -> str:
        if not query:
            return "Error: content (search query) is required"
        items = await self._mem.recall(query)
        if not items:
            return f"No memories matching: {query}"
        lines = []
        for it in items:
            lines.append(f"[#{it['id']}] [{it['category']}] {it['content']}")
        return "\n".join(lines)

    async def _categories(self) -> str:
        cats = await self._mem.get_categories()
        if not cats:
            return "No memory categories yet."
        lines = []
        for c in cats:
            summary = f" - {c['summary']}" if c["summary"] else ""
            lines.append(f"- {c['name']} ({c['item_count']} items){summary}")
        return "Memory categories:\n" + "\n".join(lines)

    async def _forget(self, item_id: int | None) -> str:
        if item_id is None:
            return "Error: item_id is required"
        if await self._mem.forget(item_id):
            return f"Removed item #{item_id}"
        return f"Item #{item_id} not found"
