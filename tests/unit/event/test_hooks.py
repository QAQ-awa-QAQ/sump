"""事件钩子系统测试：HookSystem / EventBus / Agent 生命周期事件"""

import sqlite3

import pytest

from sump.agent import Agent
from sump.event import AgentEvents, HookSystem, get_event_bus
from sump.event.bus import EventBus


class _FakeEmbedder:
    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[float(len(t)), 1.0, 0.0] for t in texts]


class _ReplyBackend:
    """返回固定回复，捕获对话。"""

    def __init__(self, reply: str = "ok") -> None:
        self._reply = reply

    async def chat(self, messages: list[dict], tools=None):
        return {"content": self._reply, "tool_calls": None, "reasoning_content": None}

    async def chat_stream(self, messages: list[dict]):
        yield {"type": "content", "text": self._reply}

    async def chat_flash(
        self, text: str, *, max_tokens: int = 256, temperature: float = 0.3
    ) -> str:
        return "safe"


class _ToolThenReplyBackend:
    """第一次返回工具调用，第二次返回最终回复。"""

    def __init__(self) -> None:
        self._chat_calls = 0

    async def chat(self, messages: list[dict], tools=None):
        self._chat_calls += 1
        if self._chat_calls == 1:
            return {
                "content": "",
                "tool_calls": [
                    {"id": "t1", "function": {"name": "no_such_tool", "arguments": "{}"}}
                ],
                "reasoning_content": None,
            }
        return {"content": "final reply", "tool_calls": None, "reasoning_content": None}

    async def chat_stream(self, messages: list[dict]):
        yield {"type": "content", "text": "final reply"}

    async def chat_flash(
        self, text: str, *, max_tokens: int = 256, temperature: float = 0.3
    ) -> str:
        return "safe"


class TestHookSystem:
    @pytest.mark.asyncio
    async def test_on_emit_sync_and_async(self):
        hs = HookSystem()
        seen: list[tuple[str, int]] = []
        hs.on("evt", lambda **kw: seen.append(("sync", kw["x"])))

        async def cb(**kw):
            seen.append(("async", kw["x"]))

        hs.on("evt", cb)
        await hs.emit("evt", x=1)
        assert seen == [("sync", 1), ("async", 1)]

    @pytest.mark.asyncio
    async def test_no_listener_returns_empty(self):
        hs = HookSystem()
        assert await hs.emit("nope") == []


class TestEventBus:
    @pytest.mark.asyncio
    async def test_on_emit(self, tmp_path):
        bus = EventBus(str(tmp_path / "event.db"))
        got: list[int] = []
        bus.on("e", lambda **kw: got.append(kw["v"]), consumer="c1")
        await bus.emit("e", v=42)
        assert got == [42]

    @pytest.mark.asyncio
    async def test_emit_records_journal(self, tmp_path):
        db_path = str(tmp_path / "event.db")
        bus = EventBus(db_path)
        bus.on("e", lambda **kw: None, consumer="c1")
        await bus.emit("e", v=1)

        conn = sqlite3.connect(db_path)
        try:
            assert conn.execute("SELECT COUNT(*) FROM event_log").fetchone()[0] == 1
            rows = conn.execute(
                "SELECT consumer, status FROM event_consumption"
            ).fetchall()
            assert rows == [("c1", "ok")]
        finally:
            conn.close()

    @pytest.mark.asyncio
    async def test_emit_isolates_subscriber_error(self, tmp_path):
        bus = EventBus(str(tmp_path / "event.db"))
        got: list[int] = []

        def boom(**kw):
            raise RuntimeError("x")

        bus.on("e", boom, consumer="bad")
        bus.on("e", lambda **kw: got.append(1), consumer="good")
        await bus.emit("e")
        assert got == [1]


class TestAgentEvents:
    @pytest.mark.asyncio
    async def test_message_and_reply_events(self, config):
        bus = get_event_bus()
        received: list[dict] = []
        replies: list[dict] = []
        bus.on(AgentEvents.MESSAGE_RECEIVED, lambda **kw: received.append(kw), consumer="t")
        bus.on(AgentEvents.REPLY, lambda **kw: replies.append(kw), consumer="t")

        agent = Agent(config, deep_embedder=_FakeEmbedder())
        agent.llm._backend = _ReplyBackend("你好，我是 SUMP")

        async for _ in agent.run_stream("你好"):
            pass

        assert [r["content"] for r in received] == ["你好"]
        assert [r["content"] for r in replies] == ["你好，我是 SUMP"]
        assert received[0]["session_id"] == "default"

    @pytest.mark.asyncio
    async def test_tool_events(self, config):
        bus = get_event_bus()
        tool_calls: list[dict] = []
        tool_results: list[dict] = []
        replies: list[dict] = []
        bus.on(AgentEvents.TOOL_CALL, lambda **kw: tool_calls.append(kw), consumer="t")
        bus.on(AgentEvents.TOOL_RESULT, lambda **kw: tool_results.append(kw), consumer="t")
        bus.on(AgentEvents.REPLY, lambda **kw: replies.append(kw), consumer="t")

        agent = Agent(config, deep_embedder=_FakeEmbedder())
        agent.llm._backend = _ToolThenReplyBackend()

        async for _ in agent.run_stream("帮我执行"):
            pass

        assert tool_calls[0]["name"] == "no_such_tool"
        assert "未注册" in tool_results[0]["content"]
        assert replies[0]["content"] == "final reply"
