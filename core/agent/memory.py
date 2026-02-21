"""Memory system for persistent agent memory.

Three-layer hierarchy:
  1. Resource layer - Raw data (messages table, daily notes, MEMORY.md)
  2. Item layer    - Extracted facts/insights (memory_items table)
  3. Category layer - Auto-organized topic groups (memory_categories table)
"""

import asyncio
import re
from datetime import datetime, timedelta
from pathlib import Path

_MAX_LONG_TERM_MEMORY_CHARS = 4000
_MAX_TODAY_NOTES_CHARS = 3000
_MAX_KB_OVERVIEW_CHARS = 2500
_LEGACY_TOPIC_LINE_RE = re.compile(
    r"^\s*-\s*\d{2}:\d{2}\s*\[[^\]]+\]\s*(?:Topic:|Note:\s*New\s*topic\s*discussed:)\s*",
    re.IGNORECASE,
)


def _ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _clip_middle(text: str, max_chars: int) -> str:
    """Clip long text while preserving both beginning and recent tail context."""
    if len(text) <= max_chars:
        return text
    marker = "\n...[truncated for prompt]...\n"
    keep = max_chars - len(marker)
    if keep <= 40:
        return text[:max_chars]
    head = keep // 2
    tail = keep - head
    return text[:head] + marker + text[-tail:]


class MemoryStore:
    """Persistent memory: files (resource layer) + SQLite (item/category layers)."""

    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.memory_dir = _ensure_dir(workspace / "memory")
        self.daily_dir = _ensure_dir(self.memory_dir / "daily")
        self.memory_file = self.memory_dir / "MEMORY.md"
        self._db = None

    def _get_db(self):
        if self._db is None:
            from core.storage.db import get_db
            self._db = get_db(self.workspace)
        return self._db

    # ==================== Resource Layer (files) ====================

    def read_long_term(self) -> str:
        if self.memory_file.exists():
            return self.memory_file.read_text(encoding="utf-8")
        return ""

    def write_long_term(self, content: str) -> None:
        self.memory_file.write_text(content, encoding="utf-8")

    def read_today(self) -> str:
        today_file = self.daily_dir / f"{_today()}.md"
        if today_file.exists():
            return today_file.read_text(encoding="utf-8")
        return ""

    def append_today(self, content: str) -> None:
        today_file = self.daily_dir / f"{_today()}.md"
        if today_file.exists():
            existing = today_file.read_text(encoding="utf-8")
            content = existing + "\n" + content
        else:
            content = f"# {_today()}\n\n{content}"
        today_file.write_text(content, encoding="utf-8")

    def append_today_note(self, content: str) -> None:
        """Append a line under today's Notes section."""
        self._append_today_section("Notes", content)

    def ensure_daily_note(self) -> None:
        """Create today's daily note from template if it doesn't exist yet."""
        today_file = self.daily_dir / f"{_today()}.md"
        if today_file.exists():
            self._sanitize_legacy_daily_content(today_file)
            return

        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        weekday_str = now.strftime("%A")

        # Try user-provided template
        template_file = self.memory_dir / "daily_template.md"
        if template_file.exists():
            template = template_file.read_text(encoding="utf-8")
        else:
            template = "# {date} ({weekday})\n\n## Notes\n\n## Learnings\n"

        content = template.replace("{date}", date_str).replace("{weekday}", weekday_str)
        today_file.write_text(content, encoding="utf-8")
        self._sanitize_legacy_daily_content(today_file)

    def _append_today_section(self, section: str, content: str) -> None:
        entry = content.strip()
        if not entry:
            return

        self.ensure_daily_note()
        today_file = self.daily_dir / f"{_today()}.md"
        self._sanitize_legacy_daily_content(today_file)
        text = today_file.read_text(encoding="utf-8") if today_file.exists() else ""
        lines = text.splitlines()
        entry_lines = entry.splitlines()
        section_header = f"## {section}"

        section_idx = next((i for i, line in enumerate(lines) if line.strip() == section_header), -1)
        if section_idx < 0:
            if lines and lines[-1].strip():
                lines.append("")
            lines.append(section_header)
            lines.append("")
            lines.extend(entry_lines)
        else:
            next_section_idx = next(
                (i for i in range(section_idx + 1, len(lines)) if lines[i].startswith("## ")),
                len(lines),
            )
            insert_at = next_section_idx
            if insert_at > section_idx + 1 and lines[insert_at - 1].strip():
                lines.insert(insert_at, "")
                insert_at += 1
            lines[insert_at:insert_at] = entry_lines

        today_file.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")

    def _sanitize_legacy_daily_content(self, file_path: Path) -> None:
        if not file_path.exists():
            return

        text = file_path.read_text(encoding="utf-8")
        lines = text.splitlines()
        kept: list[str] = []
        skipping_conversations = False

        for line in lines:
            stripped = line.strip()
            if stripped.startswith("## "):
                if stripped == "## Conversations":
                    skipping_conversations = True
                    continue
                skipping_conversations = False

            if skipping_conversations:
                continue
            if _LEGACY_TOPIC_LINE_RE.match(line):
                continue
            kept.append(line)

        normalized: list[str] = []
        prev_blank = False
        for line in kept:
            blank = not line.strip()
            if blank and prev_blank:
                continue
            normalized.append(line)
            prev_blank = blank

        cleaned = "\n".join(normalized).strip() + "\n"
        if cleaned != text:
            file_path.write_text(cleaned, encoding="utf-8")

    def get_recent_memories(self, days: int = 7) -> str:
        memories = []
        today = datetime.now().date()
        for i in range(days):
            date = today - timedelta(days=i)
            file_path = self.daily_dir / f"{date.strftime('%Y-%m-%d')}.md"
            if file_path.exists():
                memories.append(file_path.read_text(encoding="utf-8"))
        return "\n\n---\n\n".join(memories)

    # ==================== Item Layer (SQLite) ====================

    async def remember(self, content: str, category: str = "uncategorized", source: str = "conversation") -> int:
        """Extract and store a fact/insight."""
        return await self._get_db().add_memory_item(content, category, source)

    async def forget(self, item_id: int) -> bool:
        """Remove a memory item."""
        return await self._get_db().remove_memory_item(item_id)

    async def recall(self, query: str, limit: int = 10) -> list[dict]:
        """Search memory items by keyword."""
        return await self._get_db().search_memory_items(query, limit)

    async def recall_category(self, category: str, limit: int = 20) -> list[dict]:
        """Get all items in a category."""
        return await self._get_db().get_memory_items(category, limit)

    # ==================== Category Layer (SQLite) ====================

    async def get_categories(self) -> list[dict]:
        """Get all memory categories with summaries."""
        return await self._get_db().get_categories()

    async def set_category_summary(self, name: str, summary: str) -> None:
        """Update a category's summary text."""
        await self._get_db().update_category_summary(name, summary)

    # ==================== Context Assembly ====================

    def get_memory_context(self) -> str:
        """Synchronous context for system prompt (file-based layers only)."""
        parts = []
        long_term = self.read_long_term()
        if long_term:
            parts.append("## Long-term Memory\n" + _clip_middle(long_term, _MAX_LONG_TERM_MEMORY_CHARS))
        today = self.read_today()
        if today:
            parts.append("## Today's Notes\n" + _clip_middle(today, _MAX_TODAY_NOTES_CHARS))
        return "\n\n".join(parts) if parts else ""

    async def get_full_memory_context(self) -> str:
        """Async context including all 3 layers for system prompt."""
        parts = []

        # Resource layer: files
        long_term = self.read_long_term()
        if long_term:
            parts.append("## Long-term Memory\n" + _clip_middle(long_term, _MAX_LONG_TERM_MEMORY_CHARS))

        today = self.read_today()
        if today:
            parts.append("## Today's Notes\n" + _clip_middle(today, _MAX_TODAY_NOTES_CHARS))

        # Category layer: topic overview with top items
        try:
            # Bound DB context assembly so prompt generation never stalls.
            overview = await asyncio.wait_for(
                self._get_db().get_memory_overview(),
                timeout=1.5,
            )
            if overview:
                parts.append("## Knowledge Base\n" + _clip_middle(overview, _MAX_KB_OVERVIEW_CHARS))
        except (asyncio.TimeoutError, Exception):
            pass  # DB not ready yet, skip

        return "\n\n".join(parts) if parts else ""
