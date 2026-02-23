from __future__ import annotations

import pytest

from core.bus.events import InboundMessage, OutboundMessage
from core.bus.queue import MessageBus
from core.storage.db import Database


@pytest.mark.asyncio
async def test_message_bus_queue_limits_are_applied() -> None:
    bus = MessageBus(inbound_maxsize=7, outbound_maxsize=9)
    assert bus.inbound.maxsize == 7
    assert bus.outbound.maxsize == 9


@pytest.mark.asyncio
async def test_message_bus_no_loss_under_burst_within_limits() -> None:
    bus = MessageBus(inbound_maxsize=20, outbound_maxsize=20)

    inbound_payloads = [f"in-{i}" for i in range(10)]
    for idx, payload in enumerate(inbound_payloads):
        await bus.publish_inbound(
            InboundMessage(
                channel="telegram",
                sender_id=f"user-{idx}",
                chat_id="chat-1",
                content=payload,
            )
        )

    inbound_received = [await bus.consume_inbound() for _ in inbound_payloads]
    assert [m.content for m in inbound_received] == inbound_payloads

    outbound_payloads = [f"out-{i}" for i in range(10)]
    for payload in outbound_payloads:
        await bus.publish_outbound(
            OutboundMessage(channel="telegram", chat_id="chat-1", content=payload)
        )

    outbound_received = [await bus.consume_outbound() for _ in outbound_payloads]
    assert [m.content for m in outbound_received] == outbound_payloads


@pytest.mark.asyncio
async def test_database_sets_reliability_pragmas_on_init(tmp_path) -> None:
    db = Database(tmp_path)
    conn = await db._ensure_init()

    journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    synchronous = conn.execute("PRAGMA synchronous").fetchone()[0]
    busy_timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]

    assert str(journal_mode).lower() == "wal"
    assert int(synchronous) == 1  # NORMAL
    assert int(busy_timeout) == 5000


@pytest.mark.asyncio
async def test_database_reinit_preserves_existing_data(tmp_path) -> None:
    first = Database(tmp_path)
    await first._ensure_init()
    await first.log_message("telegram", "c1", "u1", "user", "persist me")

    second = Database(tmp_path)
    conn = await second._ensure_init()
    count = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    latest = conn.execute("SELECT content FROM messages ORDER BY id DESC LIMIT 1").fetchone()[0]

    assert count >= 1
    assert latest == "persist me"
