"""事件总线测试（广播 + 记账）"""

import pytest

from sump.event.bus import EventBus


@pytest.mark.asyncio
async def test_emit_notifies_subscribers(tmp_path):
    bus = EventBus(str(tmp_path / "event.db"))
    received: list[dict] = []

    async def handler(**kwargs):
        received.append(kwargs)

    bus.on("test.event", handler, consumer="t")
    results = await bus.emit("test.event", x=1, y="a")
    assert received == [{"x": 1, "y": "a"}]
    assert results == [None]  # handler 无返回值


@pytest.mark.asyncio
async def test_sync_and_async_callbacks(tmp_path):
    bus = EventBus(str(tmp_path / "event.db"))
    calls: list[str] = []

    def sync_cb(**kwargs):
        calls.append("sync")
        return "sync-result"

    async def async_cb(**kwargs):
        calls.append("async")
        return "async-result"

    bus.on("e", sync_cb, consumer="s")
    bus.on("e", async_cb, consumer="a")
    results = await bus.emit("e")
    assert calls == ["sync", "async"]
    assert results == ["sync-result", "async-result"]


@pytest.mark.asyncio
async def test_subscriber_error_does_not_break_others(tmp_path):
    bus = EventBus(str(tmp_path / "event.db"))
    calls: list[str] = []

    def bad(**kwargs):
        raise RuntimeError("boom")

    def good(**kwargs):
        calls.append("good")
        return "ok"

    bus.on("e", bad, consumer="bad")
    bus.on("e", good, consumer="good")
    results = await bus.emit("e")
    assert calls == ["good"]
    assert results == ["ok"]


@pytest.mark.asyncio
async def test_no_subscribers_returns_empty(tmp_path):
    bus = EventBus(str(tmp_path / "event.db"))
    assert await bus.emit("nobody.listens") == []
