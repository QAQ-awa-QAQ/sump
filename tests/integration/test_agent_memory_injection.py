"""Agent 记忆接入端到端测试：验证召回记忆真的进入 LLM 输入，以及写读闭环。"""

import pytest

from sump.agent import Agent
from sump.memory.session_memory import SessionMemory
from sump.tools.builtin.memory_consolidation import MemoryConsolidationTool


class _FakeEmbedder:
    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[float(len(t)), 1.0, 0.0] for t in texts]


class _CaptureBackend:
    """捕获 LLM 收到的 messages，返回空回复。"""

    def __init__(self) -> None:
        self.messages_seen: list[list[dict]] = []

    async def chat(self, messages: list[dict], tools=None):
        self.messages_seen.append(messages)
        return {
            "content": "ok",
            "tool_calls": None,
            "reasoning_content": None,
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }

    async def chat_stream(self, messages: list[dict]):
        self.messages_seen.append(messages)
        yield {"type": "content", "text": "ok"}

    async def chat_flash(self, text: str, *, max_tokens: int = 256, temperature: float = 0.3) -> str:
        return "new"


class _SeqLLM:
    """巩固用：按顺序返回预设 JSON。"""

    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.idx = 0

    async def chat_flash(self, text: str, *, max_tokens: int = 256, temperature: float = 0.3) -> str:
        resp = self.responses[min(self.idx, len(self.responses) - 1)]
        self.idx += 1
        return resp


class TestAgentMemoryInjection:
    @pytest.mark.asyncio
    async def test_recall_injected_into_llm(self, config):
        agent = Agent(config, deep_embedder=_FakeEmbedder())
        backend = _CaptureBackend()
        agent.llm._backend = backend

        # 预置深层记忆
        await agent.deep_memory.store(
            "k1", "用户在做 SUMP 项目", priority=90, embedding=[1.0, 0.0, 0.0]
        )

        async for _ in agent.run_stream("我在做什么项目"):
            pass

        assert backend.messages_seen, "LLM 未被调用"
        first_messages = backend.messages_seen[0]
        assert first_messages[0]["role"] == "system"
        assert "用户在做 SUMP 项目" in first_messages[0]["content"]

    @pytest.mark.asyncio
    async def test_write_read_loop(self, config):
        """写读闭环：睡眠巩固写入的记忆，下一次对话能被召回。"""
        # 造会话
        session_mem = SessionMemory(config.get("memory.session.db_path"))
        session_mem.save_message("s1", "user", "我喜欢 Python 编程")
        session_mem.save_message("s1", "assistant", "好的")
        session_mem.upsert_session_name("s1", "测试")

        # 跑一次睡眠巩固（写入浅层 → 深层）
        llm = _SeqLLM([
            '{"important": true, "affects_next": false, "beneficial": false, '
            '"memories": [{"category": "语义", "content": "用户喜欢 Python 编程", "priority": 85}]}',
            '{"scenes": []}',
            '{"items": [{"id": 1, "important": true, "affects_future": true, '
            '"beneficial_agent": true, "priority": 90}]}',
            '{"decisions": [{"id": "1", "action": "store", "target_keys": [], "merged_content": null}]}',
            '{"conflicts": []}',
        ])
        tool = MemoryConsolidationTool(config, llm, deep_embedder=_FakeEmbedder())
        result = await tool.execute()
        assert "提取 1 条" in result
        assert "升级 1 条" in result

        # 下一次对话：召回巩固写入的记忆
        agent = Agent(config, deep_embedder=_FakeEmbedder())
        backend = _CaptureBackend()
        agent.llm._backend = backend

        async for _ in agent.run_stream("我喜欢的编程语言是什么"):
            pass

        assert backend.messages_seen, "LLM 未被调用"
        system_content = backend.messages_seen[0][0]["content"]
        assert "Python" in system_content, f"召回的记忆未进入输入：{system_content}"

