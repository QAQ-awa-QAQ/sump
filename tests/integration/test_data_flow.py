"""数据流转集成测试：追踪数据在所有交换环节的形态与去向

覆盖链路：
- 对话消息：输入 → 内存上下文 → 会话库 → 重载 → LLM 输入
- 图片直通：块数组 → JSON 持久化 → 重载 → 历史内联策略 → LLM 输入
- 工具调用：LLM tool_call → 执行 → tool 消息配对 → 落库 → 下一轮 LLM 输入
- 安全审批：挂起 → 批准 → tool 消息替换 → 库更新 → 延续执行
- 全局设置：settings.json → Config → 客户端 → 请求参数（含热更新）
- 资产库：字节 → 文件 + 索引 + FTS → 检索 → 更新 → 软删除 → 对账
- 事件总线：emit → journal 存档 + 消费者记账
- QQ 通道：OneBot 图片段 → base64 直通 → Agent 输入 → 回复 → 发回 QQ
"""

import asyncio
import json
import sqlite3
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sump.agent import Agent
from sump.assets import AssetStore
from sump.config import Config
from sump.core.models.deepseek import DeepSeekClient
from sump.event import AgentEvents, get_event_bus
from sump.settings import save_settings

IMG = "data:image/png;base64,iVBORw0KGgo="


class _FakeEmbedder:
    """模拟 embedding，避免测试联网/加载模型。"""

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[float(len(t)), 1.0, 0.0] for t in texts]


class FlowBackend:
    """可追踪的 LLM 后端：记录每次请求的 messages，支持延迟与预设响应。"""

    def __init__(
        self,
        chat_responses: list[dict] | None = None,
        stream_texts: list[str] | None = None,
        delay: float = 0.0,
    ) -> None:
        self.chat_responses = chat_responses or [{"content": "收到", "tool_calls": None}]
        self.stream_texts = stream_texts or ["收到"]
        self.delay = delay
        self.calls: list[dict] = []
        self._chat_idx = 0

    async def chat(self, messages, *, stream=False, tools=None):
        if self.delay:
            await asyncio.sleep(self.delay)
        self.calls.append({"messages": messages, "tools": tools})
        resp = self.chat_responses[min(self._chat_idx, len(self.chat_responses) - 1)]
        self._chat_idx += 1
        return {
            "content": resp.get("content", ""),
            "reasoning_content": resp.get("reasoning_content"),
            "tool_calls": resp.get("tool_calls"),
            "usage": resp.get("usage", {}),
        }

    async def chat_stream(self, messages):
        if self.delay:
            await asyncio.sleep(self.delay)
        for text in self.stream_texts:
            yield {"type": "content", "text": text}

    async def chat_flash(self, text, *, max_tokens=256, temperature=0.3):
        return "ok"


def _make_agent(config, backend=None) -> Agent:
    """构造测试 Agent：隔离外部依赖 + 关闭内部评估（确定性）。"""
    config._data.setdefault("evaluation", {})["enabled"] = False
    agent = Agent(config, deep_embedder=_FakeEmbedder())
    agent._mcp_connected = True  # 跳过 MCP 连接（conftest 已禁用，这里双保险）
    if backend is not None:
        agent.llm._backend = backend
    return agent


async def _collect(agen) -> list[dict]:
    return [event async for event in agen]


class TestMessageDataFlow:
    @pytest.mark.asyncio
    async def test_input_to_db_to_llm(self, config):
        """消息轨迹：输入 → 内存 → 会话库 → 重载 → LLM 输入。"""
        backend = FlowBackend(stream_texts=["你好呀"])
        agent = _make_agent(config, backend)
        await _collect(agent.run_stream("你好"))

        # 环节 1：内存上下文
        assert [(m.role, m.content) for m in agent.ctx.messages] == [
            ("user", "你好"), ("assistant", "你好呀"),
        ]
        # 环节 2：SQLite 落库
        rows = agent.memory.load_messages("default")
        assert [(r["role"], r["content"]) for r in rows] == [
            ("user", "你好"), ("assistant", "你好呀"),
        ]

        # 环节 3：新实例重载历史并送 LLM（剔除 system 看对话部分）
        backend2 = FlowBackend(stream_texts=["继续收到"])
        agent2 = _make_agent(config, backend2)
        await _collect(agent2.run_stream("继续"))
        llm_msgs = [m for m in backend2.calls[0]["messages"] if m["role"] != "system"]
        assert [(m["role"], m["content"]) for m in llm_msgs] == [
            ("user", "你好"), ("assistant", "你好呀"), ("user", "继续"),
        ]

    @pytest.mark.asyncio
    async def test_image_block_to_db_to_llm(self, config):
        """图片轨迹：直通块数组 → JSON 持久化 → 重载 → 历史策略 → LLM 输入。"""
        backend = FlowBackend(stream_texts=["看到了"])
        agent = _make_agent(config, backend)
        await _collect(agent.run_stream("看这张图", images=[IMG]))

        # 内存：块数组
        assert isinstance(agent.ctx.messages[0].content, list)
        # 落库：JSON 字符串（可直接查库验证存储形态）
        db_path = str(config.get("memory.session.db_path"))
        with sqlite3.connect(db_path) as db:
            raw = db.execute("SELECT content FROM messages ORDER BY id LIMIT 1").fetchone()[0]
        assert raw.startswith("[{")
        assert IMG in raw
        # 读回：还原为块数组
        loaded = agent.memory.load_messages("default")
        assert loaded[0]["content"][1]["image_url"]["url"] == IMG

        # 新实例重载：再发一条纯文本 → 最近一条带图消息仍内联图片
        backend2 = FlowBackend(stream_texts=["嗯"])
        agent2 = _make_agent(config, backend2)
        await _collect(agent2.run_stream("什么颜色"))
        first_user = next(m for m in backend2.calls[0]["messages"] if m["role"] == "user")
        assert isinstance(first_user["content"], list)
        assert first_user["content"][1]["image_url"]["url"] == IMG

    @pytest.mark.asyncio
    async def test_tool_call_data_flow(self, config):
        """工具轨迹：tool_call → 执行 → tool 消息配对 → 落库 → 下一轮 LLM 输入。"""
        backend = FlowBackend(chat_responses=[
            {"content": "", "tool_calls": [{
                "id": "call_1", "type": "function",
                "function": {"name": "shell", "arguments": '{"command": "echo flow-test"}'},
            }]},
            {"content": "", "tool_calls": None},
        ], stream_texts=["完成"])
        agent = _make_agent(config, backend)
        agent.on_security_check = lambda cmd, summary, danger: True  # 自动批准（CLI 模式）
        events = await _collect(agent.run_stream("执行 echo"))
        types = [e["type"] for e in events]
        assert "tool_call" in types and "tool_result" in types

        # 第二轮 LLM 输入：assistant(tool_calls) + tool 消息（tool_call_id 配对）
        second_msgs = backend.calls[1]["messages"]
        tool_msg = next(m for m in second_msgs if m["role"] == "tool")
        assert tool_msg["tool_call_id"] == "call_1"
        assert "flow-test" in tool_msg["content"]

        # 落库一致：tool 消息与最终回复都在
        rows = agent.memory.load_messages("default")
        db_tool = next(r for r in rows if r["role"] == "tool")
        assert db_tool["tool_call_id"] == "call_1"
        assert rows[-1]["content"] == "完成"

    @pytest.mark.asyncio
    async def test_approval_data_flow(self, config):
        """审批轨迹：挂起 → 批准 → tool 消息替换 → 库更新 → 延续执行。"""
        backend = FlowBackend(chat_responses=[
            {"content": "", "tool_calls": [{
                "id": "tc_9", "type": "function",
                "function": {"name": "shell", "arguments": '{"command": "rm -f no_such_file_xyz"}'},
            }]},
            {"content": "", "tool_calls": None},
        ], stream_texts=["已处理"])
        agent = _make_agent(config, backend)  # 无回调 → API 模式挂起
        events = await _collect(agent.run_stream("删除文件"))
        sec = next(e for e in events if e["type"] == "security_check" and e.get("call_id"))
        call_id = sec["call_id"]
        assert agent.lookup_pending_call(call_id)

        # 挂起时：库中 tool 消息是"⛔ 待确认"占位
        rows = agent.memory.load_messages("default")
        pending_msg = next(r for r in rows if r["role"] == "tool")
        assert "⛔" in pending_msg["content"]

        # 批准 → 执行 → 库中 tool 消息被替换
        await agent.approve_command(call_id, True)
        rows2 = agent.memory.load_messages("default")
        replaced = next(r for r in rows2 if r["role"] == "tool")
        assert "⛔" not in replaced["content"]

        # 延续执行 → 第二轮 LLM 收到替换后的结果（不是占位）
        await _collect(agent.run_core())
        tool_msg = next(m for m in backend.calls[1]["messages"] if m["role"] == "tool")
        assert "⛔" not in tool_msg["content"]


class TestSettingsDataFlow:
    @pytest.mark.asyncio
    async def test_settings_to_request_kwargs(self, tmp_path, monkeypatch):
        """设置轨迹：settings.json → Config → 客户端 → 请求参数；热更新同样生效。"""
        monkeypatch.setenv("SUMP_SETTINGS_FILE", str(tmp_path / "settings.json"))
        save_settings({"deepseek.model": "deepseek-v4-pro"})
        cfg = Config()
        client = DeepSeekClient(cfg)
        assert client._model == "deepseek-v4-pro"

        response = MagicMock()
        response.choices = [MagicMock()]
        response.choices[0].message.content = "hi"
        response.choices[0].message.tool_calls = None
        response.usage = None

        with patch.object(
            client._client.chat.completions, "create", new=AsyncMock(return_value=response)
        ) as mock_create:
            await client.chat([{"role": "user", "content": "hi"}])
        assert mock_create.call_args.kwargs["model"] == "deepseek-v4-pro"

        # 热更新轨迹：apply_settings 后请求使用新值
        client.apply_settings({"model": "m-hot"})
        with patch.object(
            client._client.chat.completions, "create", new=AsyncMock(return_value=response)
        ) as mock_create2:
            await client.chat([{"role": "user", "content": "hi"}])
        assert mock_create2.call_args.kwargs["model"] == "m-hot"

    @pytest.mark.asyncio
    async def test_qq_agent_created_after_save_gets_fresh_key(self, config):
        """复现线上 401：设置保存早于 QQ 首条消息时，新建的 QQ Agent 必须用最新 Key。"""
        from sump.plugins.builtin.napcat_plugin import NapCatPlugin

        plugin = NapCatPlugin(config)  # 启动快照：此时无 Key（占位）
        save_settings({"deepseek.api_key": "sk-after-save"})
        agent = plugin._get_agent("private_1")  # 保存之后才创建（首条消息到达）
        assert agent.llm._backend._api_key == "sk-after-save"


class TestAssetDataFlow:
    @pytest.mark.asyncio
    async def test_asset_tool_flow_via_agent(self, config):
        """资产轨迹（工具层）：msg:N 取图 → 保存 → 检索路径 → 软删除。"""
        agent = _make_agent(config)
        agent.ctx.add_user_message("图", images=[IMG])  # 预置带图消息

        save_result = await agent.tools.get("asset_save").execute(
            source="msg:1", description="测试表情", tags="测试"
        )
        assert "已保存" in save_result

        found = await agent.tools.get("asset_search").execute(query="测试表情")
        assert "测试表情" in found and "路径：" in found

        # 更新（重命名）→ 旧词不再命中、新词命中
        asset_id = int(found.split("[资产 #")[1].split("]")[0])
        updated = await agent.tools.get("asset_update").execute(
            id=asset_id, description="改名后的表情"
        )
        assert "改名后的表情" in updated

        deleted = await agent.tools.get("asset_delete").execute(id=asset_id)
        assert "已删除" in deleted
        assert "没有匹配" in await agent.tools.get("asset_search").execute(query="改名后的表情")

    def test_asset_store_full_lifecycle(self, tmp_path):
        """资产轨迹（存储层）：字节 → 文件 + 索引 + FTS → 更新 → 软删除 → 对账。"""
        store = AssetStore(str(tmp_path / "assets"), str(tmp_path / "assets.db"))
        entry = store.save_bytes(
            b"\x89PNG\r\n\x1a\n" + b"data", description="猫猫", tags=["搞笑"]
        )
        # 文件落盘 + 索引可检索
        assert (tmp_path / "assets" / entry["filename"]).is_file()
        assert len(store.search("猫猫")) == 1

        # 更新描述 → FTS 同步（新词命中）
        store.update(entry["id"], description="更新的猫猫描述")
        assert len(store.search("更新的猫猫")) == 1

        # 软删除 → 文件进 .trash，索引清除
        store.delete(entry["id"])
        assert store.search("") == []
        assert len(list((tmp_path / "assets" / ".trash").iterdir())) == 1

        # 对账扫描：.trash 不会被复活
        store2 = AssetStore(str(tmp_path / "assets"), str(tmp_path / "assets.db"))
        assert store2.search("") == []


class TestEventDataFlow:
    @pytest.mark.asyncio
    async def test_emit_to_journal_and_consumption(self, config):
        """事件轨迹：emit → event_log 存档 + 订阅者消费记账。"""
        bus = get_event_bus()
        received: list[int] = []
        bus.on("test_event", lambda **kw: received.append(kw.get("value")), consumer="collector")
        await bus.emit("test_event", value=7)
        assert received == [7]

        with sqlite3.connect(str(bus._journal._path)) as db:  # noqa: SLF001
            log = db.execute("SELECT event, payload FROM event_log").fetchall()
            cons = db.execute(
                "SELECT consumer, status FROM event_consumption"
            ).fetchall()
        assert log[0][0] == "test_event"
        assert json.loads(log[0][1])["value"] == 7
        assert ("collector", "ok") in cons

    @pytest.mark.asyncio
    async def test_agent_events_recorded(self, config):
        """对话事件轨迹：Agent 生命周期事件进入事件账本。"""
        backend = FlowBackend(stream_texts=["好的"])
        agent = _make_agent(config, backend)
        await _collect(agent.run_stream("你好"))
        bus = get_event_bus()
        with sqlite3.connect(str(bus._journal._path)) as db:  # noqa: SLF001
            names = [r[0] for r in db.execute("SELECT event FROM event_log").fetchall()]
        assert AgentEvents.MESSAGE_RECEIVED in names
        assert AgentEvents.REPLY in names


class TestQQDataFlow:
    @pytest.mark.asyncio
    async def test_qq_image_message_roundtrip(self, config, monkeypatch):
        """QQ 轨迹：OneBot 图片段 → base64 直通 → Agent 输入 → 回复 → 发回 QQ。"""
        from sump.plugins.builtin.napcat_plugin import NapCatPlugin

        plugin = NapCatPlugin(config)
        sent_raw: list[str] = []

        class _FakeWS:
            async def send(self, raw: str) -> None:
                sent_raw.append(raw)

        plugin._ws = _FakeWS()
        backend = FlowBackend(stream_texts=["好看！"])
        agent = _make_agent(config, backend)

        def fake_get_agent(sid: str):
            agent.switch_session(sid)  # 真实插件会切换会话，桩不能省
            return agent

        monkeypatch.setattr(plugin, "_get_agent", fake_get_agent)
        monkeypatch.setattr(plugin, "_is_owner", lambda uid: True)

        async def fake_download(url: str) -> str:
            return IMG

        monkeypatch.setattr(plugin, "_download_image_data_url", fake_download)

        await plugin._handle_message({
            "post_type": "message",
            "message_type": "private",
            "user_id": 111,
            "message": [
                {"type": "image", "data": {"url": "http://qq/img"}},
                {"type": "text", "data": {"text": "看看这张图"}},
            ],
        })

        # Agent 输入：块数组（文本 + 图片 data URL）
        first_user = agent.ctx.messages[0]
        assert isinstance(first_user.content, list)
        assert first_user.content[1]["image_url"]["url"] == IMG
        # 回复经 REPLY 钩子发回 QQ（fake ws 收到的 send_msg 含回复文本）
        assert any("好看" in raw for raw in sent_raw)
