"""评估系统测试：InternalEvaluator / Arbiter / Executor 集成"""

import pytest

from sump.core.context import Context
from sump.core.executor import Executor
from sump.core.planner import Plan
from sump.evaluation.arbiter import Arbiter
from sump.evaluation.internal import InternalEvaluator
from sump.tools.base import Tool
from sump.tools.registry import ToolRegistry


class _FakeLLM:
    def __init__(self, raw: str) -> None:
        self.raw = raw

    async def chat_flash(
        self, text: str, *, max_tokens: int = 256, temperature: float = 0.3
    ) -> str:
        return self.raw


class TestInternalEvaluator:
    @pytest.mark.asyncio
    async def test_evaluate_done(self):
        ev = InternalEvaluator(
            _FakeLLM('{"done": true, "score": 0.9, "issues": [], "suggestions": []}')
        )
        r = await ev.evaluate("任务", "结果")
        assert r["done"] is True
        assert r["score"] == 0.9

    @pytest.mark.asyncio
    async def test_evaluate_bad_json_fallback(self):
        ev = InternalEvaluator(_FakeLLM("not json"))
        r = await ev.evaluate("任务", "结果")
        assert r["done"] is False
        assert r["score"] == 0.0

    @pytest.mark.asyncio
    async def test_evaluate_no_llm(self):
        ev = InternalEvaluator()
        assert await ev.evaluate("任务", "结果") == {
            "done": False,
            "score": 0.0,
            "issues": [],
            "suggestions": [],
        }


class TestArbiter:
    @pytest.mark.asyncio
    async def test_finish_when_done(self):
        v = await Arbiter().arbitrate({"done": True, "score": 0.2, "issues": []})
        assert v["action"] == "finish"

    @pytest.mark.asyncio
    async def test_finish_when_high_score(self):
        v = await Arbiter().arbitrate({"done": False, "score": 0.9, "issues": []})
        assert v["action"] == "finish"

    @pytest.mark.asyncio
    async def test_continue(self):
        v = await Arbiter().arbitrate({"done": False, "score": 0.6, "issues": []})
        assert v["action"] == "continue"

    @pytest.mark.asyncio
    async def test_retry(self):
        v = await Arbiter().arbitrate({"done": False, "score": 0.2, "issues": ["信息不足"]})
        assert v["action"] == "retry"


class _DummyTool(Tool):
    name = "dummy"
    description = "dummy"
    parameters = {"type": "object", "properties": {}}

    async def execute(self, **kwargs):
        return "ok"


class _ToolCallLLM:
    """每次都返回工具调用。"""

    def __init__(self) -> None:
        self.chat_calls = 0
        self.stream_called = False

    async def chat_full(self, messages, tools=None):
        self.chat_calls += 1
        return {
            "content": "",
            "tool_calls": [
                {"id": "t1", "function": {"name": "no_such_tool", "arguments": "{}"}}
            ],
            "reasoning_content": None,
        }

    async def chat_stream(self, messages):
        self.stream_called = True
        yield {"type": "content", "text": "done"}


class _DoneEvaluator:
    async def evaluate(self, task, result):
        return {"done": True, "score": 0.9, "issues": [], "suggestions": []}


class _FinishArbiter:
    async def arbitrate(self, internal, external=None):
        return {"proceed": False, "action": "finish", "reason": "done"}


class TestExecutorEvaluation:
    @pytest.mark.asyncio
    async def test_finish_early_after_tool_call(self, config):
        ctx = Context(config)
        ctx.add_user_message("帮我执行任务")

        tools = ToolRegistry()
        tools.register(_DummyTool())

        llm = _ToolCallLLM()
        executor = Executor(
            ctx, llm, tools, evaluator=_DoneEvaluator(), arbiter=_FinishArbiter()
        )

        events = []
        async for e in executor.execute(Plan(tools_enabled=True, max_rounds=10)):
            events.append(e)

        # 第一轮工具调用后评估判定完成，不再进入第二轮 chat_full
        assert llm.chat_calls == 1
        assert llm.stream_called is True
        assert any(e.get("type") == "tool_call" for e in events)
