"""模型输出标记文本清洗测试（伪调用文本禁止外泄、禁止进入上下文）"""

from unittest.mock import AsyncMock, MagicMock, patch

from sump.core.executor import Executor
from sump.core.models.deepseek import DeepSeekClient, sanitize_marked_output
from sump.tools.registry import ToolRegistry

# 运行时拼接构造标记形态（避免源码中出现完整标记字面量）
_W = "\uff5c"                   # 全角竖线（模型泄漏时的典型分隔符）
_B = "\u007c"                   # 半角竖线（变体）
_T = f"{_W}{_W}DSML{_W}{_W}"    # 典型标记词元


def _marked_block() -> str:
    """模拟泄漏的多行伪调用块（覆盖真实形态：标记词元包裹伪 XML 标签）。"""
    return "\n".join([
        f"<{_T} calls>",
        f'<{_T} invoke name="shell">',
        f'<{_T} parameter name="command" string="true">ls -la</{_T} parameter>',
        f"</{_T} invoke>",
        f"</{_T} calls>",
    ])


def _mock_response(content: str) -> MagicMock:
    """构造非流式响应 mock。"""
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.content = content
    response.choices[0].message.tool_calls = None
    response.usage = None
    return response


class TestSanitizeMarkedOutput:
    """sanitize_marked_output 基础行为。"""

    def test_drops_marked_block_keeps_normal(self):
        """标记块整行剔除，正常文本行保留。"""
        text = f"好的，我来看看\n{_marked_block()}\n完成"
        assert sanitize_marked_output(text) == "好的，我来看看\n完成"

    def test_pure_block_becomes_empty(self):
        """整段都是标记块 → 清洗为空串。"""
        assert sanitize_marked_output(_marked_block()) == ""

    def test_plain_text_untouched(self):
        """普通文本（提及 DSML 字样但无标记符号）原样返回。"""
        text = "我不该用 DSML 这类格式，应该走标准工具调用协议。"
        assert sanitize_marked_output(text) == text

    def test_halfwidth_variant(self):
        """半角竖线变体同样清洗。"""
        assert sanitize_marked_output(f"{_B}DSML{_B} calls>") == ""

    def test_inline_marked_line_removed(self):
        """标记出现在行中：该行整体剔除（宁可多删，绝不泄漏）。"""
        text = f"内容 A\n前缀 {_T} 后缀\n内容 B"
        assert sanitize_marked_output(text) == "内容 A\n内容 B"


class TestChatCleansMarkedContent:
    """chat() 出口：标记文本被清洗，且不解析为工具调用。"""

    async def test_marked_block_cleaned_not_parsed(self, config):
        client = DeepSeekClient(config)
        with patch.object(
            client._client.chat.completions, "create",
            new=AsyncMock(return_value=_mock_response(_marked_block())),
        ):
            result = await client.chat([{"role": "user", "content": "hi"}])

        assert result["tool_calls"] is None
        assert result["content"] == ""

    async def test_normal_content_untouched(self, config):
        client = DeepSeekClient(config)
        with patch.object(
            client._client.chat.completions, "create",
            new=AsyncMock(return_value=_mock_response("正常回复，含 DSML 字样")),
        ):
            result = await client.chat([{"role": "user", "content": "hi"}])

        assert result["content"] == "正常回复，含 DSML 字样"


class TestChatStreamCleansChunks:
    """chat_stream()：逐块清洗，整块被清空时不产出空事件。"""

    async def test_marked_chunk_dropped(self, config):
        client = DeepSeekClient(config)

        def _chunk(text: str) -> MagicMock:
            chunk = MagicMock()
            delta = MagicMock()
            delta.reasoning_content = None
            delta.tool_calls = None
            delta.content = text
            chunk.choices = [MagicMock()]
            chunk.choices[0].delta = delta
            return chunk

        async def _fake_stream():
            yield _chunk(f"{_T} calls>")
            yield _chunk("正常 token")

        with patch.object(
            client._client.chat.completions, "create",
            new=AsyncMock(return_value=_fake_stream()),
        ):
            events = [
                ev async for ev in client.chat_stream([{"role": "user", "content": "hi"}])
            ]

        contents = [ev["text"] for ev in events if ev["type"] == "content"]
        assert contents == ["正常 token"]


class TestExecutorFulltextFallback:
    """executor：跨块残片在全文级被兜底清掉，不写入上下文。"""

    async def test_cross_chunk_fragment_stripped(self, config, ctx):
        class _FragmentedLLM:
            async def chat_stream(self, messages):
                yield {"type": "content", "text": f"开场白\n{_W}{_W}D"}
                yield {"type": "content", "text": f"SML{_W}{_W} calls>\n结尾"}

        executor = Executor(ctx, _FragmentedLLM(), ToolRegistry())
        async for _ in executor._stream_final():
            pass

        assistant = [m for m in ctx.messages if m.role == "assistant"]
        assert assistant
        assert assistant[-1].content == "开场白\n结尾"
