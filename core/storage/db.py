"""SQLite storage for message history, memory hierarchy, cron state, and search."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

_db_instances: dict[str, "Database"] = {}


def get_db(workspace: Path) -> "Database":
    """Get or create a Database instance for a workspace."""
    key = str(workspace.resolve())
    if key not in _db_instances:
        _db_instances[key] = Database(workspace)
    return _db_instances[key]


class Database:
    """SQLite database for persistent storage."""

    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.db_path = workspace / "db" / "yacb.db"
        self._db: sqlite3.Connection | None = None
        self._initialized = False
        self._fts_enabled = True

    async def _ensure_init(self) -> sqlite3.Connection:
        if self._db is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._db = sqlite3.connect(str(self.db_path))
            # Reliability defaults: allow concurrent readers and reduce lock thrash.
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA synchronous=NORMAL")
            self._db.execute("PRAGMA busy_timeout=5000")
        if not self._initialized:
            await self._create_tables()
            self._initialized = True
        return self._db

    async def _create_tables(self) -> None:
        db = self._db
        assert db is not None

        # --- Resource layer: raw conversations ---
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel TEXT NOT NULL,
                chat_id TEXT NOT NULL,
                sender_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp TEXT NOT NULL
            )
            """
        )

        # --- Item layer: extracted facts/insights ---
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS memory_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT 'uncategorized',
                source TEXT NOT NULL DEFAULT 'conversation',
                confidence REAL NOT NULL DEFAULT 1.0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                access_count INTEGER NOT NULL DEFAULT 0,
                last_accessed TEXT
            )
            """
        )

        # --- Category layer: auto-organized topic groups ---
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS memory_categories (
                name TEXT PRIMARY KEY,
                summary TEXT NOT NULL DEFAULT '',
                item_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )

        db.execute(
            """
            CREATE TABLE IF NOT EXISTS cron_jobs (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                schedule_json TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                state_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                delete_after_run INTEGER NOT NULL DEFAULT 0
            )
            """
        )

        # FTS5 is optional. If unavailable, fall back to LIKE search.
        try:
            db.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
                    content, channel, chat_id, sender_id,
                    content='messages',
                    content_rowid='id'
                )
                """
            )
            db.execute(
                """
                CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
                    INSERT INTO messages_fts(rowid, content, channel, chat_id, sender_id)
                    VALUES (new.id, new.content, new.channel, new.chat_id, new.sender_id);
                END
                """
            )

            db.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS items_fts USING fts5(
                    content, category,
                    content='memory_items',
                    content_rowid='id'
                )
                """
            )
            db.execute(
                """
                CREATE TRIGGER IF NOT EXISTS items_ai AFTER INSERT ON memory_items BEGIN
                    INSERT INTO items_fts(rowid, content, category)
                    VALUES (new.id, new.content, new.category);
                END
                """
            )
            db.execute(
                """
                CREATE TRIGGER IF NOT EXISTS items_au AFTER UPDATE ON memory_items BEGIN
                    INSERT INTO items_fts(items_fts, rowid, content, category)
                    VALUES ('delete', old.id, old.content, old.category);
                    INSERT INTO items_fts(rowid, content, category)
                    VALUES (new.id, new.content, new.category);
                END
                """
            )
            self._fts_enabled = True
        except sqlite3.OperationalError:
            self._fts_enabled = False

        # --- Token usage tracking ---
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS token_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel TEXT NOT NULL,
                chat_id TEXT NOT NULL,
                model TEXT NOT NULL,
                tier TEXT NOT NULL DEFAULT '',
                prompt_tokens INTEGER NOT NULL DEFAULT 0,
                completion_tokens INTEGER NOT NULL DEFAULT 0,
                total_tokens INTEGER NOT NULL DEFAULT 0,
                cost REAL NOT NULL DEFAULT 0.0,
                timestamp TEXT NOT NULL
            )
            """
        )
        db.commit()

    # ==================== Messages (Resource Layer) ====================

    async def log_message(
        self, channel: str, chat_id: str, sender_id: str, role: str, content: str
    ) -> None:
        db = await self._ensure_init()
        db.execute(
            "INSERT INTO messages (channel, chat_id, sender_id, role, content, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
            (channel, chat_id, sender_id, role, content, datetime.now().isoformat()),
        )
        db.commit()

    async def search_messages(
        self,
        query: str,
        limit: int = 20,
        channel: str | None = None,
        chat_id: str | None = None,
    ) -> list[dict]:
        db = await self._ensure_init()
        where_parts: list[str] = []
        params: list[object] = []
        if channel is not None:
            where_parts.append("m.channel=?")
            params.append(channel)
        if chat_id is not None:
            where_parts.append("m.chat_id=?")
            params.append(chat_id)

        if self._fts_enabled:
            where = ""
            if where_parts:
                where = " AND " + " AND ".join(where_parts)
            cursor = db.execute(
                f"""
                SELECT m.channel, m.chat_id, m.sender_id, m.role, m.content, m.timestamp
                FROM messages_fts f
                JOIN messages m ON f.rowid = m.id
                WHERE messages_fts MATCH ?
                {where}
                ORDER BY m.id DESC
                LIMIT ?
                """,
                [query, *params, limit],
            )
        else:
            where = ""
            if channel is not None:
                where += " AND channel=?"
            if chat_id is not None:
                where += " AND chat_id=?"
            cursor = db.execute(
                f"""
                SELECT channel, chat_id, sender_id, role, content, timestamp
                FROM messages
                WHERE content LIKE ?
                {where}
                ORDER BY id DESC
                LIMIT ?
                """,
                [f"%{query}%", *params, limit],
            )
        rows = cursor.fetchall()
        return [
            {
                "channel": r[0],
                "chat_id": r[1],
                "sender_id": r[2],
                "role": r[3],
                "content": r[4],
                "timestamp": r[5],
            }
            for r in rows
        ]

    async def get_recent_messages(
        self,
        channel: str | None = None,
        chat_id: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        db = await self._ensure_init()
        if channel is None and chat_id is None:
            cursor = db.execute(
                "SELECT channel, chat_id, role, content, timestamp FROM messages ORDER BY id DESC LIMIT ?",
                (limit,),
            )
        elif channel is not None and chat_id is not None:
            cursor = db.execute(
                """
                SELECT channel, chat_id, role, content, timestamp
                FROM messages
                WHERE channel=? AND chat_id=?
                ORDER BY id DESC
                LIMIT ?
                """,
                (channel, chat_id, limit),
            )
        else:
            return []
        rows = cursor.fetchall()
        return [
            {
                "channel": r[0],
                "chat_id": r[1],
                "role": r[2],
                "content": r[3],
                "timestamp": r[4],
            }
            for r in reversed(rows)
        ]

    # ==================== Memory Items (Item Layer) ====================

    async def add_memory_item(
        self, content: str, category: str = "uncategorized", source: str = "conversation", confidence: float = 1.0
    ) -> int:
        """Store an extracted fact/insight."""
        db = await self._ensure_init()
        now = datetime.now().isoformat()
        cursor = db.execute(
            """INSERT INTO memory_items (content, category, source, confidence, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (content, category, source, confidence, now, now),
        )
        await self._ensure_category(category)
        db.commit()
        return int(cursor.lastrowid)

    async def update_memory_item(self, item_id: int, content: str | None = None, category: str | None = None) -> None:
        db = await self._ensure_init()
        now = datetime.now().isoformat()
        if content is not None:
            db.execute("UPDATE memory_items SET content=?, updated_at=? WHERE id=?", (content, now, item_id))
        if category is not None:
            db.execute("UPDATE memory_items SET category=?, updated_at=? WHERE id=?", (category, now, item_id))
            await self._ensure_category(category)
        await self._refresh_category_counts()
        db.commit()

    async def remove_memory_item(self, item_id: int) -> bool:
        db = await self._ensure_init()
        cursor = db.execute("DELETE FROM memory_items WHERE id=?", (item_id,))
        if self._fts_enabled:
            db.execute("INSERT INTO items_fts(items_fts) VALUES ('rebuild')")
        await self._refresh_category_counts()
        db.commit()
        return cursor.rowcount > 0

    async def search_memory_items(self, query: str, limit: int = 20) -> list[dict]:
        """Search memory items by FTS if available, otherwise LIKE."""
        db = await self._ensure_init()
        if self._fts_enabled:
            cursor = db.execute(
                """
                SELECT m.id, m.content, m.category, m.source, m.confidence, m.created_at
                FROM items_fts f
                JOIN memory_items m ON f.rowid = m.id
                WHERE items_fts MATCH ?
                ORDER BY m.id DESC
                LIMIT ?
                """,
                (query, limit),
            )
        else:
            cursor = db.execute(
                """
                SELECT id, content, category, source, confidence, created_at
                FROM memory_items
                WHERE content LIKE ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (f"%{query}%", limit),
            )
        rows = cursor.fetchall()
        return [
            {
                "id": r[0],
                "content": r[1],
                "category": r[2],
                "source": r[3],
                "confidence": r[4],
                "created_at": r[5],
            }
            for r in rows
        ]

    async def get_memory_items(self, category: str | None = None, limit: int = 50) -> list[dict]:
        """Get memory items, optionally filtered by category."""
        db = await self._ensure_init()
        if category:
            cursor = db.execute(
                "SELECT id, content, category, source, confidence, created_at FROM memory_items WHERE category=? ORDER BY id DESC LIMIT ?",
                (category, limit),
            )
        else:
            cursor = db.execute(
                "SELECT id, content, category, source, confidence, created_at FROM memory_items ORDER BY id DESC LIMIT ?",
                (limit,),
            )
        rows = cursor.fetchall()
        ids = [r[0] for r in rows]
        if ids:
            placeholders = ",".join("?" * len(ids))
            now = datetime.now().isoformat()
            db.execute(
                f"UPDATE memory_items SET access_count = access_count + 1, last_accessed = ? WHERE id IN ({placeholders})",
                [now] + ids,
            )
            db.commit()
        return [
            {
                "id": r[0],
                "content": r[1],
                "category": r[2],
                "source": r[3],
                "confidence": r[4],
                "created_at": r[5],
            }
            for r in rows
        ]

    # ==================== Categories (Category Layer) ====================

    async def _ensure_category(self, name: str) -> None:
        """Create category if it doesn't exist."""
        db = await self._ensure_init()
        now = datetime.now().isoformat()
        db.execute(
            "INSERT OR IGNORE INTO memory_categories (name, created_at, updated_at) VALUES (?, ?, ?)",
            (name, now, now),
        )

    async def _refresh_category_counts(self) -> None:
        """Recalculate item_count for all categories."""
        db = await self._ensure_init()
        now = datetime.now().isoformat()
        db.execute(
            """
            UPDATE memory_categories SET
                item_count = (SELECT COUNT(*) FROM memory_items WHERE memory_items.category = memory_categories.name),
                updated_at = ?
            """,
            (now,),
        )

    async def update_category_summary(self, name: str, summary: str) -> None:
        db = await self._ensure_init()
        now = datetime.now().isoformat()
        db.execute(
            "UPDATE memory_categories SET summary=?, updated_at=? WHERE name=?",
            (summary, now, name),
        )
        db.commit()

    async def get_categories(self) -> list[dict]:
        """Get all categories with summaries and counts."""
        db = await self._ensure_init()
        await self._refresh_category_counts()
        db.commit()
        cursor = db.execute(
            "SELECT name, summary, item_count, updated_at FROM memory_categories WHERE item_count > 0 ORDER BY item_count DESC"
        )
        rows = cursor.fetchall()
        return [{"name": r[0], "summary": r[1], "item_count": r[2], "updated_at": r[3]} for r in rows]

    async def get_memory_overview(self) -> str:
        """Build a text overview of all categories and their top items for context injection."""
        categories = await self.get_categories()
        if not categories:
            return ""
        parts = []
        for cat in categories:
            header = f"### {cat['name']} ({cat['item_count']} items)"
            if cat["summary"]:
                header += f"\n{cat['summary']}"
            items = await self.get_memory_items(category=cat["name"], limit=5)
            item_lines = [f"- {it['content']}" for it in items]
            parts.append(header + "\n" + "\n".join(item_lines))
        return "\n\n".join(parts)

    # ==================== Token Usage ====================

    async def log_token_usage(
        self,
        channel: str,
        chat_id: str,
        model: str,
        tier: str,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        cost: float,
    ) -> None:
        db = await self._ensure_init()
        db.execute(
            """INSERT INTO token_usage
               (channel, chat_id, model, tier, prompt_tokens, completion_tokens, total_tokens, cost, timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                channel,
                chat_id,
                model,
                tier,
                prompt_tokens,
                completion_tokens,
                total_tokens,
                cost,
                datetime.now().isoformat(),
            ),
        )
        db.commit()

    async def get_usage_summary(self, chat_id: str | None = None, days: int = 30) -> list[dict]:
        """Get usage grouped by model, optionally filtered by chat_id."""
        db = await self._ensure_init()
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()

        if chat_id:
            cursor = db.execute(
                """SELECT model, tier,
                          SUM(prompt_tokens) as prompt_tok,
                          SUM(completion_tokens) as comp_tok,
                          SUM(total_tokens) as total_tok,
                          SUM(cost) as total_cost,
                          COUNT(*) as calls
                   FROM token_usage
                   WHERE chat_id=? AND timestamp >= ?
                   GROUP BY model
                   ORDER BY total_cost DESC""",
                (chat_id, cutoff),
            )
        else:
            cursor = db.execute(
                """SELECT model, tier,
                          SUM(prompt_tokens) as prompt_tok,
                          SUM(completion_tokens) as comp_tok,
                          SUM(total_tokens) as total_tok,
                          SUM(cost) as total_cost,
                          COUNT(*) as calls
                   FROM token_usage
                   WHERE timestamp >= ?
                   GROUP BY model
                   ORDER BY total_cost DESC""",
                (cutoff,),
            )
        rows = cursor.fetchall()
        return [
            {
                "model": r[0],
                "tier": r[1],
                "prompt_tokens": r[2],
                "completion_tokens": r[3],
                "total_tokens": r[4],
                "cost": r[5],
                "calls": r[6],
            }
            for r in rows
        ]

    async def get_usage_total(self, days: int = 30) -> dict:
        """Get total usage across all models."""
        db = await self._ensure_init()
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        cursor = db.execute(
            """SELECT SUM(prompt_tokens), SUM(completion_tokens), SUM(total_tokens),
                      SUM(cost), COUNT(*)
               FROM token_usage WHERE timestamp >= ?""",
            (cutoff,),
        )
        row = cursor.fetchone()
        if not row or row[4] == 0:
            return {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "cost": 0.0,
                "calls": 0,
            }
        return {
            "prompt_tokens": row[0] or 0,
            "completion_tokens": row[1] or 0,
            "total_tokens": row[2] or 0,
            "cost": row[3] or 0.0,
            "calls": row[4] or 0,
        }

    # ==================== Lifecycle ====================

    async def close(self) -> None:
        if self._db:
            self._db.close()
            self._db = None
            self._initialized = False
