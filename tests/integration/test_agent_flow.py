"""Agent 集成测试 —— run_stream 端到端流程"""

import pytest

from sump.agent import Agent
from sump.types import Message


class TestAgentRunStream:
    """测试 Agent.run_stream 核心流程。"""

    @pytest.mark.asyncio
    async def test_simple_response(self, config):
        """无工具时的纯文本回复流程。"""
        agent = Agent(config)
        agent.llm._backend = _FakeDeepSeek(stream_texts=["Hello, world!"])

        events = []
        async for event in agent.run_stream("hi"):
            events.append(event)

        content_events = [e for e in events if e["type"] == "content"]
        assert len(content_events) > 0
        assert any("Hello" in e.get("text", "") for e in content_events)

    @pytest.mark.asyncio
    async def test_tool_call_flow(self, config):
        """工具调用流程：LLM 返回 tool_call -> 安全检查 -> 执行 -> 继续。"""
        agent = Agent(config)
        agent.llm._backend = _FakeDeepSeek(
            chat_responses=[
                {
                    "content": "",
                    "tool_calls": [{
                        "id": "call_1", "type": "function",
                        "function": {
                            "name": "shell",
                            "arguments": '{"command": "echo hello"}',
                        },
                    }],
                    "reasoning_content": None,
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                },
                {"content": "Done!", "tool_calls": None, "reasoning_content": None,
                 "usage": {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13}},
            ],
        )

        def auto_approve(_cmd: str, _summary: str, _danger: str) -> bool:
            return True

        agent.on_security_check = auto_approve

        events = []
        async for event in agent.run_stream("run echo"):
            events.append(event)

        tool_call_events = [e for e in events if e["type"] == "tool_call"]
        assert len(tool_call_events) > 0
        assert tool_call_events[0]["name"] == "shell"

    @pytest.mark.asyncio
    async def test_session_persistence(self, config):
        """测试会话创建和切换。"""
        agent = Agent(config)
        sid = agent.new_session()
        assert len(sid) == 8
        assert agent.session_id == sid

        # 切换会话
        sid2 = agent.new_session()
        assert sid2 != sid
        assert agent.session_id == sid2

        # default 会话始终存在
        sessions = agent.memory.list_sessions()
        sids = [s["id"] for s in sessions]
        assert "default" in sids


class TestAgentSecurity:
    """测试安全审批流程。"""

    @pytest.mark.asyncio
    async def test_approve_command(self, config):
        """测试 approve_command：挂起 -> 审批 -> 执行。"""
        agent = Agent(config)
        from sump.tools.builtin.shell import ShellTool
        agent._pending_approvals["test_call"] = {
            "command": "echo test",
            "tool": ShellTool(),
            "tool_call_id": "tc_1",
            "args": {"command": "echo test"},
        }
        agent.ctx.add_tool_message("tc_1", "\u26d4 安全审查待确认 | call_id: test_call")

        result = await agent.approve_command("test_call", True)
        assert "echo" in result.lower() or "test" in result.lower()

    def test_lookup_pending(self, config):
        agent = Agent(config)
        agent._pending_approvals["abc"] = {}
        assert agent.lookup_pending_call("abc") is True
        assert agent.lookup_pending_call("xyz") is False


# ------------------------------------------------------------------
# Fake DeepSeek for integration tests
# ------------------------------------------------------------------

class _FakeDeepSeek:
    """模拟 DeepSeekClient，避免真实 API 调用。"""

    def __init__(self, stream_texts=None, chat_responses=None):
        self._stream_texts = stream_texts or ["mock"]
        self._chat_responses = chat_responses or [{"content": "mock", "tool_calls": None}]
        self._chat_idx = 0

    async def chat(self, messages, *, stream=False, tools=None):
        resp = self._chat_responses[min(self._chat_idx, len(self._chat_responses) - 1)]
        self._chat_idx += 1
        return {
            "content": resp.get("content", ""),
            "reasoning_content": resp.get("reasoning_content"),
            "tool_calls": resp.get("tool_calls"),
            "usage": resp.get("usage", {}),
        }

    async def chat_text(self, messages):
        return (await self.chat(messages))["content"]

    async def chat_stream(self, messages):
        for text in self._stream_texts:
            yield {"type": "content", "text": text}
