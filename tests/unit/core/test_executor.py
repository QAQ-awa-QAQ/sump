"""执行器测试"""

from types import SimpleNamespace
from typing import Any

import pytest

from sump.core.context import Context
from sump.core.executor import Executor
from sump.core.planner import Plan
from sump.tools.base import Tool
from sump.tools.registry import ToolRegistry
from tests.conftest import MockLLMClient


class _FakeShell(Tool):
    """测试用 shell 替身（不启动子进程）。"""
    name = "shell"
    description = "fake shell"
    parameters = {
        "type": "object",
        "properties": {"command": {"type": "string", "description": "命令"}},
        "required": ["command"],
    }

    async def execute(self, command: str = "", **kwargs: Any) -> str:
        return f"fake: {command}"


def _patch_security(monkeypatch: pytest.MonkeyPatch) -> None:
    """把 shell 安全检查替换为固定放行，隔离 Judge/LLM 依赖。"""

    async def _fake_analyze(self: Executor, command: str):
        return {}, {}, SimpleNamespace(
            command=command, summary="测试", danger="low",
            concerns=[], verdict="safe",
        ), True

    monkeypatch.setattr(Executor, "_analyze_security", _fake_analyze)


class TestExecutor:
    @pytest.mark.asyncio
    async def test_execute_no_tools(self, config, ctx):
        """无工具 Plan：应直接流式回复。"""
        llm = MockLLMClient([{"content": "hello", "tool_calls": None}])
        tools = ToolRegistry()
        executor = Executor(ctx, llm, tools)
        plan = Plan(action="respond", tools_enabled=False)

        events = []
        async for event in executor.execute(plan):
            events.append(event)

        content_events = [e for e in events if e["type"] == "content"]
        assert len(content_events) > 0

    @pytest.mark.asyncio
    async def test_execute_with_tools_no_registry(self, config, ctx):
        """tools_enabled=True 但 ToolRegistry 为空：退化为无工具流。"""
        llm = MockLLMClient([{"content": "hi", "tool_calls": None}])
        tools = ToolRegistry()
        executor = Executor(ctx, llm, tools)
        plan = Plan(action="respond", tools_enabled=True)

        events = []
        async for event in executor.execute(plan):
            events.append(event)
        # 应直接走 _stream_final
        assert any(e["type"] == "content" for e in events)


class TestToolsFirstRoundOnly:
    """工具定义传递开关：默认仅首轮；关闭后每轮都传。"""

    @staticmethod
    def _shell_call_responses() -> list[dict]:
        return [
            {"content": "", "tool_calls": [{
                "id": "t1", "type": "function",
                "function": {"name": "shell", "arguments": '{"command": "echo hi"}'},
            }]},
            {"content": "完成", "tool_calls": None},
        ]

    @pytest.mark.asyncio
    async def test_default_only_first_round(self, ctx, monkeypatch):
        """默认（开关开启）：首轮带工具定义，后续轮不带。"""
        _patch_security(monkeypatch)
        tools = ToolRegistry()
        tools.register(_FakeShell())
        llm = MockLLMClient(self._shell_call_responses())
        executor = Executor(ctx, llm, tools, security_check=lambda *_: True)
        plan = Plan(action="respond", tools_enabled=True, max_rounds=3)

        async for _ in executor.execute(plan):
            pass

        assert len(llm.calls) >= 2
        assert llm.calls[0]["tools"] is not None
        assert llm.calls[1]["tools"] is None

    @pytest.mark.asyncio
    async def test_disabled_keeps_tools_every_round(self, ctx, monkeypatch):
        """关闭开关：后续轮次仍带工具定义。"""
        _patch_security(monkeypatch)
        tools = ToolRegistry()
        tools.register(_FakeShell())
        llm = MockLLMClient(self._shell_call_responses())
        executor = Executor(
            ctx, llm, tools, security_check=lambda *_: True,
            tools_first_round_only=False,
        )
        plan = Plan(action="respond", tools_enabled=True, max_rounds=3)

        async for _ in executor.execute(plan):
            pass

        assert len(llm.calls) >= 2
        assert llm.calls[0]["tools"] is not None
        assert llm.calls[1]["tools"] is not None


class TestToolLoopTermination:
    """执行循环终止条件：仅"真正挂起等审批"才终止（回归：非 shell 工具曾误判）。"""

    @pytest.mark.asyncio
    async def test_non_shell_tool_continues_loop(self, ctx, tools):
        """非 shell 工具执行后继续回轮，产出最终回复。"""
        llm = MockLLMClient([
            {"content": "", "tool_calls": [{
                "id": "t1", "type": "function",
                "function": {"name": "echo", "arguments": '{"text": "hi"}'},
            }]},
            {"content": "完成", "tool_calls": None},
        ])
        executor = Executor(ctx, llm, tools)
        plan = Plan(action="respond", tools_enabled=True, max_rounds=3)

        events = []
        async for event in executor.execute(plan):
            events.append(event)

        assert len(llm.calls) == 2                          # 回轮发生
        assert any(e["type"] == "content" for e in events)  # 最终回复产出

    @pytest.mark.asyncio
    async def test_shell_pending_still_breaks(self, ctx, monkeypatch):
        """shell 真正挂起等审批：本轮终止，不继续回轮。"""
        _patch_security(monkeypatch)
        tools = ToolRegistry()
        tools.register(_FakeShell())
        llm = MockLLMClient([
            {"content": "", "tool_calls": [{
                "id": "t1", "type": "function",
                "function": {"name": "shell", "arguments": '{"command": "echo hi"}'},
            }]},
            {"content": "完成", "tool_calls": None},
        ])
        pending_args: list[tuple] = []
        executor = Executor(
            ctx, llm, tools,
            security_check=lambda *_: None,                # 无意见 → 挂起
            on_approval_pending=lambda *a: pending_args.append(a),
        )
        plan = Plan(action="respond", tools_enabled=True, max_rounds=3)

        async for _ in executor.execute(plan):
            pass

        assert len(llm.calls) == 1          # 未回轮
        assert pending_args                 # 挂起回调被触发
