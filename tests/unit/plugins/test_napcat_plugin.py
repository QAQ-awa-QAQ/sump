"""NapCat 插件测试：OneBot 解析、会话路由、钩子闭环"""

from types import SimpleNamespace

import pytest

from sump.event import AgentEvents
from sump.plugins.builtin.napcat_plugin import NapCatPlugin


class _FakeGroupAgentWithReply:
    """模拟群聊 Agent：记录消息 + run_core 时通过钩子 emit 回复。"""

    def __init__(self, bus, session_id: str) -> None:
        self._bus = bus
        self._session_id = session_id
        self.recorded: list[str] = []
        self.ctx = SimpleNamespace(add_user_message=self.recorded.append)

    async def run_core(self):
        await self._bus.emit(
            AgentEvents.REPLY, session_id=self._session_id, content="星宝在"
        )
        if False:  # 使其成为 async generator
            yield


class TestExtractText:
    def test_string(self):
        assert NapCatPlugin._extract_text("你好") == "你好"

    def test_segments(self):
        assert NapCatPlugin._extract_text([
            {"type": "text", "data": {"text": "你好"}},
            {"type": "face", "data": {"id": "1"}},
            {"type": "text", "data": {"text": "世界"}},
        ]) == "你好世界"

    def test_non_text_and_none(self):
        assert NapCatPlugin._extract_text([{"type": "at", "data": {"qq": "123"}}]) == ""
        assert NapCatPlugin._extract_text(None) == ""


class TestHandleMessage:
    @pytest.mark.asyncio
    async def test_private_message(self, config, monkeypatch):
        plugin = NapCatPlugin(config)
        monkeypatch.setattr(plugin, "_is_owner", lambda uid: True)
        sent: list[tuple] = []

        async def fake_send(ctx, content):
            sent.append((ctx, content))

        monkeypatch.setattr(plugin, "_send", fake_send)

        calls: list[str] = []

        async def fake_run_stream(text):
            if False:
                yield

        fake_agent = SimpleNamespace(run_stream=fake_run_stream)

        def fake_get_agent(sid):
            calls.append(sid)
            return fake_agent

        monkeypatch.setattr(plugin, "_get_agent", fake_get_agent)

        received: list[dict] = []
        plugin._bus.on(
            AgentEvents.MESSAGE_RECEIVED, lambda **kw: received.append(kw), consumer="t"
        )

        await plugin._handle_message({
            "post_type": "message",
            "message_type": "private",
            "user_id": 111,
            "message": [{"type": "text", "data": {"text": "你好"}}],
        })

        assert calls == ["private_111"]
        assert received[0]["content"] == "你好"
        assert received[0]["source"] == "napcat"
        assert sent == []  # 无回复钩子，不发回

    @pytest.mark.asyncio
    async def test_group_records_message(self, config, monkeypatch):
        """群聊：记录消息；判断不插话则不回复。"""
        plugin = NapCatPlugin(config)
        recorded: list[str] = []
        run_core_calls: list[int] = []
        agent = SimpleNamespace(ctx=SimpleNamespace(add_user_message=recorded.append))

        async def fake_run_core():
            run_core_calls.append(1)
            if False:
                yield

        agent.run_core = fake_run_core
        monkeypatch.setattr(plugin, "_get_agent", lambda sid: agent)

        async def fake_should_speak(agent, text, mentioned, at_me):
            return False

        monkeypatch.setattr(plugin, "_should_speak", fake_should_speak)

        await plugin._handle_message({
            "post_type": "message",
            "message_type": "group",
            "user_id": 111,
            "group_id": 222,
            "sender": {"nickname": "小明"},
            "message": "今天天气不错",
        })

        assert recorded == ["[小明] 今天天气不错"]
        assert run_core_calls == []

    @pytest.mark.asyncio
    async def test_group_at_me_speaks(self, config, monkeypatch):
        """群聊：被 @ 必回。"""
        plugin = NapCatPlugin(config)
        recorded: list[str] = []
        run_core_calls: list[int] = []
        agent = SimpleNamespace(ctx=SimpleNamespace(add_user_message=recorded.append))

        async def fake_run_core():
            run_core_calls.append(1)
            if False:
                yield

        agent.run_core = fake_run_core
        monkeypatch.setattr(plugin, "_get_agent", lambda sid: agent)
        monkeypatch.setattr(plugin, "_is_at_me", lambda data: True)

        await plugin._handle_message({
            "post_type": "message",
            "message_type": "group",
            "user_id": 111,
            "group_id": 222,
            "sender": {"nickname": "小明"},
            "message": [{"type": "at", "data": {"qq": "10001"}}, {"type": "text", "data": {"text": "星宝在吗"}}],
        })

        assert recorded == ["[小明] 星宝在吗"]
        assert run_core_calls == [1]


class TestOnReply:
    @pytest.mark.asyncio
    async def test_routes_by_session_prefix(self, config, monkeypatch):
        plugin = NapCatPlugin(config)
        sent: list[tuple] = []

        async def fake_send(ctx, content):
            sent.append((ctx, content))

        monkeypatch.setattr(plugin, "_send", fake_send)

        await plugin._on_reply("group_123", "群回复")
        await plugin._on_reply("private_456", "私聊回复")
        await plugin._on_reply("other_1", "忽略")  # 未知前缀不发送

        assert sent == [
            ({"message_type": "group", "group_id": "123"}, "群回复"),
            ({"message_type": "private", "user_id": "456"}, "私聊回复"),
        ]


class TestRoundTrip:
    @pytest.mark.asyncio
    async def test_group_roundtrip(self, config, monkeypatch):
        """群聊 @ → 记录 + run_core → REPLY 钩子 → 发回 QQ 的闭环。"""
        plugin = NapCatPlugin(config)
        sent: list[tuple] = []

        async def fake_send(ctx, content):
            sent.append((ctx, content))

        monkeypatch.setattr(plugin, "_send", fake_send)
        monkeypatch.setattr(plugin, "_is_at_me", lambda data: True)

        agent = _FakeGroupAgentWithReply(plugin._bus, "group_123")
        monkeypatch.setattr(plugin, "_get_agent", lambda sid: agent)

        await plugin._handle_message({
            "post_type": "message",
            "message_type": "group",
            "user_id": 111,
            "group_id": 123,
            "sender": {"nickname": "小明"},
            "message": "星宝在吗",
        })

        assert sent == [({"message_type": "group", "group_id": "123"}, "星宝在")]


class TestOwnerRestriction:
    @pytest.mark.asyncio
    async def test_non_owner_rejected(self, config, monkeypatch):
        """非主人消息：拒绝执行，不驱动 Agent。"""
        plugin = NapCatPlugin(config)
        monkeypatch.setattr(plugin, "_owner_id", "999")
        sent: list[tuple] = []

        async def fake_send(ctx, content):
            sent.append((ctx, content))

        monkeypatch.setattr(plugin, "_send", fake_send)
        called: list[str] = []
        monkeypatch.setattr(plugin, "_get_agent", lambda sid: called.append(sid) or None)

        await plugin._handle_message({
            "post_type": "message",
            "message_type": "private",
            "user_id": 111,
            "message": "执行 rm -rf /",
        })

        assert called == []  # Agent 未被调用
        assert sent and "拒绝" in sent[0][1]

    @pytest.mark.asyncio
    async def test_owner_allowed(self, config, monkeypatch):
        """主人消息：正常驱动 Agent。"""
        plugin = NapCatPlugin(config)
        monkeypatch.setattr(plugin, "_owner_id", "999")
        sent: list[tuple] = []

        async def fake_send(ctx, content):
            sent.append((ctx, content))

        monkeypatch.setattr(plugin, "_send", fake_send)
        called: list[str] = []

        async def fake_run_stream(text):
            if False:
                yield

        fake_agent = SimpleNamespace(run_stream=fake_run_stream)
        monkeypatch.setattr(plugin, "_get_agent", lambda sid: called.append(sid) or fake_agent)

        await plugin._handle_message({
            "post_type": "message",
            "message_type": "private",
            "user_id": 999,
            "message": "你好",
        })

        assert called == ["private_999"]
        assert sent == []  # fake agent 不 emit 回复

    def test_is_owner(self, config):
        plugin = NapCatPlugin(config)
        plugin._owner_id = "999"
        assert plugin._is_owner("999") is True
        assert plugin._is_owner("111") is False
        # 未配置主人 → 拒绝所有人
        plugin._owner_id = ""
        assert plugin._is_owner("999") is False


class TestShouldSpeak:
    @pytest.mark.asyncio
    async def test_at_me_always_speaks(self, config):
        plugin = NapCatPlugin(config)
        agent = SimpleNamespace(llm=None)  # @ 必回，不调 flash
        assert await plugin._should_speak(agent, "在吗", False, True) is True

    @pytest.mark.asyncio
    async def test_mention_with_flash_yes(self, config):
        plugin = NapCatPlugin(config)

        async def fake_flash(prompt, *, max_tokens=256, temperature=0.3):
            return "yes"

        agent = SimpleNamespace(llm=SimpleNamespace(chat_flash=fake_flash))
        assert await plugin._should_speak(agent, "星宝帮我", True, False) is True

    @pytest.mark.asyncio
    async def test_plain_flash_no(self, config):
        plugin = NapCatPlugin(config)

        async def fake_flash(prompt, *, max_tokens=256, temperature=0.3):
            return "no"

        agent = SimpleNamespace(llm=SimpleNamespace(chat_flash=fake_flash))
        assert await plugin._should_speak(agent, "随便聊聊", False, False) is False

    @pytest.mark.asyncio
    async def test_flash_error_falls_back_to_mention(self, config):
        plugin = NapCatPlugin(config)

        async def boom(prompt, *, max_tokens=256, temperature=0.3):
            raise RuntimeError("x")

        agent = SimpleNamespace(llm=SimpleNamespace(chat_flash=boom))
        assert await plugin._should_speak(agent, "星宝", True, False) is True
        assert await plugin._should_speak(agent, "随便", False, False) is False


class TestIsAtMe:
    def test_is_at_me(self, config):
        plugin = NapCatPlugin(config)
        assert plugin._is_at_me({
            "self_id": "10001",
            "message": [
                {"type": "at", "data": {"qq": "10001"}},
                {"type": "text", "data": {"text": "在吗"}},
            ],
        }) is True
        assert plugin._is_at_me({
            "self_id": "10001",
            "message": [{"type": "text", "data": {"text": "在吗"}}],
        }) is False
        assert plugin._is_at_me({
            "self_id": "10001",
            "message": [{"type": "at", "data": {"qq": "999"}}],
        }) is False
        assert plugin._is_at_me({"self_id": "", "message": "在吗"}) is False


class TestImageExtraction:
    def test_extract_image_urls(self, config):
        assert NapCatPlugin._extract_image_urls([
            {"type": "image", "data": {"url": "http://x/a.jpg"}},
            {"type": "text", "data": {"text": "看这个"}},
        ]) == ["http://x/a.jpg"]
        assert NapCatPlugin._extract_image_urls("text") == []
        assert NapCatPlugin._extract_image_urls([{"type": "text", "data": {"text": "x"}}]) == []

    @pytest.mark.asyncio
    async def test_image_message_recorded(self, config, monkeypatch):
        """纯图片消息：下载到本地后记录为 [图片] 本地路径，不因无文本被忽略。"""
        plugin = NapCatPlugin(config)
        recorded: list[str] = []
        agent = SimpleNamespace(ctx=SimpleNamespace(add_user_message=recorded.append))
        monkeypatch.setattr(plugin, "_get_agent", lambda sid: agent)

        async def fake_download(url):
            return "/tmp/pic.jpg"

        monkeypatch.setattr(plugin, "_download_image", fake_download)

        async def fake_should_speak(agent, text, mentioned, at_me):
            return False

        monkeypatch.setattr(plugin, "_should_speak", fake_should_speak)

        await plugin._handle_message({
            "post_type": "message",
            "message_type": "group",
            "user_id": 111,
            "group_id": 222,
            "sender": {"nickname": "小明"},
            "message": [{"type": "image", "data": {"url": "http://x/pic.jpg"}}],
        })

        assert recorded == ["[小明] [图片] /tmp/pic.jpg"]

    def test_guess_image_ext(self):
        from sump.plugins.builtin.napcat_plugin import _guess_image_ext

        assert _guess_image_ext(b"\xff\xd8\xffxx") == ".jpg"
        assert _guess_image_ext(b"\x89PNG\r\n\x1a\nxx") == ".png"
        assert _guess_image_ext(b"GIF8xx") == ".gif"
        assert _guess_image_ext(b"RIFF....WEBPxx") == ".webp"
        assert _guess_image_ext(b"unknown") == ".jpg"


class TestNapCatApproval:
    @pytest.mark.asyncio
    async def test_approval_pending_pushes_to_owner(self, config, monkeypatch):
        plugin = NapCatPlugin(config)
        sent: list[tuple] = []

        async def fake_send(ctx, content):
            sent.append((ctx, content))

        monkeypatch.setattr(plugin, "_send", fake_send)

        await plugin._on_approval_pending(
            session_id="private_111",
            call_id="c1",
            command="rm -rf /",
            summary="删除文件",
            danger="high",
        )

        assert plugin._pending_approval["private_111"] == "c1"
        assert sent and "待审批" in sent[0][1]
        assert "rm -rf /" in sent[0][1]

    @pytest.mark.asyncio
    async def test_approval_response_1_approves(self, config, monkeypatch):
        plugin = NapCatPlugin(config)
        monkeypatch.setattr(plugin, "_is_owner", lambda uid: True)
        plugin._pending_approval["private_111"] = "c1"

        calls: list[tuple] = []

        async def fake_approve_and_continue(call_id, approved):
            calls.append((call_id, approved))

        agent = SimpleNamespace(approve_and_continue=fake_approve_and_continue)
        monkeypatch.setattr(plugin, "_get_agent", lambda sid: agent)
        monkeypatch.setattr(plugin, "_send", lambda ctx, content: None)

        await plugin._handle_message({
            "post_type": "message",
            "message_type": "private",
            "user_id": 111,
            "message": "1",
        })

        assert calls == [("c1", True)]

    @pytest.mark.asyncio
    async def test_approval_response_2_rejects(self, config, monkeypatch):
        plugin = NapCatPlugin(config)
        monkeypatch.setattr(plugin, "_is_owner", lambda uid: True)
        plugin._pending_approval["group_222"] = "c2"

        calls: list[tuple] = []

        async def fake_approve_and_continue(call_id, approved):
            calls.append((call_id, approved))

        agent = SimpleNamespace(approve_and_continue=fake_approve_and_continue)
        monkeypatch.setattr(plugin, "_get_agent", lambda sid: agent)
        monkeypatch.setattr(plugin, "_send", lambda ctx, content: None)

        await plugin._handle_message({
            "post_type": "message",
            "message_type": "group",
            "user_id": 999,
            "group_id": 222,
            "message": "2",
        })

        assert calls == [("c2", False)]


class TestOwnerMarker:
    @pytest.mark.asyncio
    async def test_owner_message_marked(self, config, monkeypatch):
        """主人消息带 owner_marker 标记，非主人不带。"""
        config._data.setdefault("memory", {})["owner_marker"] = "·主人"
        plugin = NapCatPlugin(config)
        monkeypatch.setattr(plugin, "_is_owner", lambda uid: uid == "999")
        recorded: list[str] = []
        agent = SimpleNamespace(ctx=SimpleNamespace(add_user_message=recorded.append))
        monkeypatch.setattr(plugin, "_get_agent", lambda sid: agent)

        async def fake_should_speak(agent, text, mentioned, at_me):
            return False

        monkeypatch.setattr(plugin, "_should_speak", fake_should_speak)

        await plugin._handle_message({
            "post_type": "message",
            "message_type": "group",
            "user_id": 999,
            "group_id": 222,
            "sender": {"nickname": "小明"},
            "message": "我喜欢 Python",
        })

        assert recorded == ["[小明·主人] 我喜欢 Python"]
