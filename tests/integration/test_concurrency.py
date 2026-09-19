"""竞态与并发集成测试：串行保护、竞争裁决、跨实例并发

重点场景：
- 同一会话并发消息 → Agent 串行锁保护，消息成对不交错
- 审批延续（run_core）与进行中对话 → 共用锁，严格串行
- 不同会话并发 → 数据隔离不串扰
- 审批超时定时器 vs 用户审批 → pop 原子性，只有一个生效
- 资产并发保存 → 内容级去重（含 IntegrityError 竞态窗口）
- 多实例并发写同库 / 事件并发记账 → 无丢失
- NapCat 同会话消息 → 插件锁串行处理
"""

import asyncio
import sqlite3
from types import SimpleNamespace

import pytest

from sump.assets import AssetStore
from sump.event import get_event_bus
from sump.plugins.builtin.napcat_plugin import NapCatPlugin
from sump.tools.builtin.shell import ShellTool
from tests.integration.test_data_flow import FlowBackend, _make_agent

PNG = b"\x89PNG\r\n\x1a\n" + b"same-content"


class TestSameSessionSerialization:
    @pytest.mark.asyncio
    async def test_concurrent_streams_serialized(self, config):
        """同一 Agent 并发两条消息：串行处理，user/assistant 严格成对。"""
        backend = FlowBackend(stream_texts=["回复"], delay=0.02)
        agent = _make_agent(config, backend)
        done: list[str] = []

        async def first():
            async for _ in agent.run_stream("第一条"):
                pass
            done.append("first")

        async def second():
            async for _ in agent.run_stream("第二条"):
                pass
            done.append("second")

        await asyncio.gather(first(), second())

        # 严格成对（无锁时会出现 user/user 交错或回复丢失）
        assert [m.role for m in agent.ctx.messages] == [
            "user", "assistant", "user", "assistant",
        ]
        user_contents = [m.content for m in agent.ctx.messages if m.role == "user"]
        assert user_contents == ["第一条", "第二条"]
        # 库与内存一致
        rows = agent.memory.load_messages("default")
        assert [r["role"] for r in rows] == ["user", "assistant", "user", "assistant"]
        assert sorted(done) == ["first", "second"]

    @pytest.mark.asyncio
    async def test_run_core_waits_for_active_stream(self, config):
        """审批延续与进行中的对话串行（run_core 等锁，不交错抢跑）。"""
        backend = FlowBackend(stream_texts=["慢速回复"], delay=0.02)
        agent = _make_agent(config, backend)
        agent._pending_approvals["c1"] = {
            "command": "echo done",
            "tool": ShellTool(),
            "tool_call_id": "tc1",
            "args": {"command": "echo done"},
        }
        agent.ctx.add_tool_message("tc1", "⛔ 安全审查待确认 | call_id: c1")

        order: list[str] = []

        async def streaming():
            async for _ in agent.run_stream("慢速对话"):
                pass
            order.append("stream")

        async def approving():
            await agent.approve_and_continue("c1", True)
            order.append("approve")

        await asyncio.gather(streaming(), approving())
        assert order == ["stream", "approve"]


class TestSessionIsolation:
    @pytest.mark.asyncio
    async def test_concurrent_sessions_isolated(self, config):
        """不同会话并发运行：各自数据正确落库，互不串扰。"""
        agent_a = _make_agent(config, FlowBackend(stream_texts=["A的回复"], delay=0.01))
        agent_a.switch_session("session_a")
        agent_b = _make_agent(config, FlowBackend(stream_texts=["B的回复"], delay=0.01))
        agent_b.switch_session("session_b")

        async def run(agent, text):
            async for _ in agent.run_stream(text):
                pass

        await asyncio.gather(run(agent_a, "A的消息"), run(agent_b, "B的消息"))

        rows_a = agent_a.memory.load_messages("session_a")
        rows_b = agent_b.memory.load_messages("session_b")
        assert [r["content"] for r in rows_a] == ["A的消息", "A的回复"]
        assert [r["content"] for r in rows_b] == ["B的消息", "B的回复"]


class TestApprovalRace:
    def _agent_with_pending(self, config, call_id: str, tc_id: str):
        agent = _make_agent(config)
        agent._pending_approvals[call_id] = {
            "command": "echo x",
            "tool": ShellTool(),
            "tool_call_id": tc_id,
            "args": {"command": "echo x"},
        }
        agent.ctx.add_tool_message(tc_id, f"⛔ 安全审查待确认 | call_id: {call_id}")
        return agent

    @pytest.mark.asyncio
    async def test_timeout_then_approve_expired(self, config):
        """超时先到：之后审批返回已过期，不重复执行。"""
        agent = self._agent_with_pending(config, "c1", "tc1")
        await agent._auto_reject("c1")
        result = await agent.approve_command("c1", True)
        assert "已过期" in result
        assert not agent.lookup_pending_call("c1")

    @pytest.mark.asyncio
    async def test_approve_then_timeout_noop(self, config):
        """审批先到：超时定时器随后触发无副作用。"""
        agent = self._agent_with_pending(config, "c2", "tc2")
        await agent.approve_command("c2", True)
        before = [m.content for m in agent.ctx.messages]
        await agent._auto_reject("c2")
        after = [m.content for m in agent.ctx.messages]
        assert before == after

    @pytest.mark.asyncio
    async def test_concurrent_approve_and_timeout_single_winner(self, config):
        """审批与超时并发：只有一个生效（pop 原子性），消息只被替换一次。"""
        agent = self._agent_with_pending(config, "c3", "tc3")
        results = await asyncio.gather(
            agent.approve_command("c3", True),
            agent._auto_reject("c3"),
            return_exceptions=True,
        )
        assert not any(isinstance(r, Exception) for r in results)
        tool_msgs = [m for m in agent.ctx.messages if m.role == "tool"]
        assert len(tool_msgs) == 1
        assert not agent.lookup_pending_call("c3")


class TestCrossInstanceConcurrency:
    @pytest.mark.asyncio
    async def test_parallel_agents_write_same_registry(self, config):
        """多 Agent 实例并发写同一会话库：消息无丢失。"""
        agents = [_make_agent(config) for _ in range(4)]

        async def writer(idx: int, agent):
            for j in range(5):
                agent.memory.save_message("shared", "user", f"agent{idx}-msg{j}")

        await asyncio.gather(*[writer(i, a) for i, a in enumerate(agents)])
        rows = agents[0].memory.load_messages("shared", limit=100)
        assert len(rows) == 20

    def test_asset_concurrent_save_dedup_window(self, tmp_path, monkeypatch):
        """资产并发去重：命中 IntegrityError 竞态窗口时返回已有条目而非崩溃。"""
        store1 = AssetStore(str(tmp_path / "assets"), str(tmp_path / "assets.db"))
        store2 = AssetStore(str(tmp_path / "assets"), str(tmp_path / "assets.db"))
        monkeypatch.setattr("sump.assets.time.time", lambda: 1234567890.0)

        first = store1.save_bytes(PNG, description="先到")
        assert first["duplicated"] is False

        # 模拟并发窗口：store2 的首次 hash 查询发生在 store1 提交之前（返回 None）
        calls = {"n": 0}
        real_find = store2.find_by_hash

        def flaky_find(digest):
            calls["n"] += 1
            return None if calls["n"] == 1 else real_find(digest)

        monkeypatch.setattr(store2, "find_by_hash", flaky_find)
        second = store2.save_bytes(PNG, description="后到")

        assert second["duplicated"] is True
        assert second["id"] == first["id"]
        # 只有一个文件、一条索引
        assert len(list((tmp_path / "assets").glob("*.png"))) == 1
        assert len(store1.search("")) == 1


class TestEventConcurrency:
    @pytest.mark.asyncio
    async def test_concurrent_emit_all_recorded(self, config):
        """并发 emit：订阅者全部收到，事件账本完整记账。"""
        bus = get_event_bus()
        seen: list[int] = []
        bus.on("race_event", lambda **kw: seen.append(kw.get("i")), consumer="collector")

        await asyncio.gather(*[bus.emit("race_event", i=i) for i in range(20)])

        assert sorted(seen) == list(range(20))
        with sqlite3.connect(str(bus._journal._path)) as db:  # noqa: SLF001
            n_log = db.execute(
                "SELECT COUNT(*) FROM event_log WHERE event = 'race_event'"
            ).fetchone()[0]
            n_cons = db.execute(
                "SELECT COUNT(*) FROM event_consumption"
            ).fetchone()[0]
        assert n_log == 20
        assert n_cons >= 20


class TestNapCatSerialization:
    @pytest.mark.asyncio
    async def test_same_group_messages_serialized(self, config, monkeypatch):
        """同群两条消息并发：插件锁保证串行处理（start/end 成对不交错）。"""
        plugin = NapCatPlugin(config)
        order: list[str] = []

        class _SlowAgent:
            def __init__(self) -> None:
                self.ctx = SimpleNamespace(add_user_message=lambda *a, **k: None)

            async def run_core(self):
                order.append("start")
                await asyncio.sleep(0.02)
                order.append("end")
                if False:  # 使其成为 async generator
                    yield

        monkeypatch.setattr(plugin, "_get_agent", lambda sid: _SlowAgent())

        async def fake_speak(*args):
            return True

        monkeypatch.setattr(plugin, "_should_speak", fake_speak)

        msg = {
            "post_type": "message",
            "message_type": "group",
            "user_id": 1,
            "group_id": 9,
            "sender": {"nickname": "x"},
            "message": "并发消息",
        }
        await asyncio.gather(
            plugin._handle_message(dict(msg)),
            plugin._handle_message(dict(msg)),
        )
        assert order == ["start", "end", "start", "end"]
