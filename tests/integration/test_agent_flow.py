"""Agent 集成测试 —— run_stream 端到端流程"""

from typing import Any

import pytest

from sump.agent import Agent
from sump.types import Message


class _FakeEmbedder:
    """模拟 embedding，避免测试联网下载模型。"""

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[float(len(t)), 1.0, 0.0] for t in texts]


class TestAgentRunStream:
    """测试 Agent.run_stream 核心流程。"""

    @pytest.mark.asyncio
    async def test_simple_response(self, config):
        """无工具时的纯文本回复流程。"""
        agent = Agent(config, deep_embedder=_FakeEmbedder())
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
        agent = Agent(config, deep_embedder=_FakeEmbedder())
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

        # 写入一条消息（触发持久化）
        agent.ctx.add_user_message("hello")

        # 切换会话
        sid2 = agent.new_session()
        assert sid2 != sid
        assert agent.session_id == sid2

        # 有消息的会话应出现在列表中
        sessions = agent.memory.list_sessions()
        sids = [s["id"] for s in sessions]
        assert sid in sids


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


class TestVisionToolRouting:
    """识图工具挂载策略：多模态主模型直读图片（图片块直发），
    不挂额外 image_vision 工具；纯文本模型挂兜底。"""

    def test_supports_vision_mapping(self):
        from sump.core.models.deepseek import supports_vision

        assert supports_vision("deepseek-flash")
        assert supports_vision("DeepSeek-Flash-2026xx")  # 大小写 / 版本化 id
        assert not supports_vision("deepseek-v4-pro")
        assert not supports_vision("")

    def test_multimodal_model_has_no_vision_tool(self, config):
        """默认模型 deepseek-flash 支持图片直通 → 不注册 image_vision。"""
        agent = Agent(config, deep_embedder=_FakeEmbedder())
        assert agent.tools.get("image_vision") is None

    def test_text_model_gets_vision_tool(self, config):
        """文本模型（deepseek-v4-pro）无法直读图片 → 挂 image_vision 兜底。"""
        config._data.setdefault("deepseek", {})["model"] = "deepseek-v4-pro"
        agent = Agent(config, deep_embedder=_FakeEmbedder())
        assert agent.tools.get("image_vision") is not None

    def test_settings_switch_syncs_vision_tool(self, config):
        """设置中心切换模型：已创建 Agent 的识图工具随之增删。"""
        agent = Agent(config, deep_embedder=_FakeEmbedder())
        assert agent.tools.get("image_vision") is None

        agent.apply_settings({"model": "deepseek-v4-pro"})
        assert agent.tools.get("image_vision") is not None

        agent.apply_settings({"model": "deepseek-flash"})
        assert agent.tools.get("image_vision") is None


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


# ------------------------------------------------------------------
# REPLY 出口清洗（伪调用标记文本绝不外发）
# ------------------------------------------------------------------

class TestReplySanitization:
    """REPLY 事件文本经过清洗：标记文本不会发到 QQ/CLI。"""

    @pytest.mark.asyncio
    async def test_marked_stream_reply_stripped(self, config):
        from sump.event import AgentEvents, get_event_bus

        # 运行时拼接构造标记形态（避免源码出现完整标记字面量）
        w = "\uff5c"
        token = f"{w}{w}DSML{w}{w}"

        agent = Agent(config, deep_embedder=_FakeEmbedder())
        agent.llm._backend = _FakeDeepSeek(stream_texts=[
            "正常开头\n",
            f"{token} calls>\n",
            "正常结尾",
        ])

        replies: list[str] = []

        async def _capture(session_id: str, content: str, **kwargs: Any) -> None:
            replies.append(content)

        get_event_bus().on(AgentEvents.REPLY, _capture, consumer="test")

        async for _ in agent.run_stream("hi"):
            pass

        assert replies == ["正常开头\n正常结尾"]


class TestToolsFirstRoundOnlyWiring:
    """agent.tools_first_round_only 配置接线到 Executor（默认开启）。"""

    def test_default_true(self, config):
        agent = Agent(config, deep_embedder=_FakeEmbedder())
        assert agent._executor._tools_first_round_only is True

    def test_config_disables(self, config):
        config._data.setdefault("agent", {})["tools_first_round_only"] = False
        agent = Agent(config, deep_embedder=_FakeEmbedder())
        assert agent._executor._tools_first_round_only is False
