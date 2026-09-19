"""Context 多模态历史测试：图片剥离策略（仅最近一条带图消息内联）"""

from sump.core.context import Context

IMG = "data:image/png;base64,AAAA"


class TestHistoryTextOnly:
    def test_text_history_unchanged(self, config):
        ctx = Context(config)
        ctx.add_user_message("你好")
        ctx.add_assistant_message("你好呀")
        assert ctx.history == [
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "你好呀"},
        ]

    def test_system_prompt_first(self, config):
        ctx = Context(config)
        ctx.set_system_prompt("你是星宝")
        ctx.add_user_message("看图", [IMG])
        history = ctx.history
        assert history[0] == {"role": "system", "content": "你是星宝"}
        assert isinstance(history[1]["content"], list)


class TestHistoryImagePolicy:
    def test_followup_keeps_latest_image(self, config):
        """带图后追问纯文本：最近一条带图消息仍内联图片。"""
        ctx = Context(config)
        ctx.add_user_message("这是什么", [IMG])
        ctx.add_assistant_message("一只猫")
        ctx.add_user_message("它的毛色呢")
        history = ctx.history
        assert isinstance(history[0]["content"], list)
        assert history[0]["content"][1]["image_url"]["url"] == IMG
        assert history[2]["content"] == "它的毛色呢"

    def test_older_images_degraded_to_placeholder(self, config):
        """更早的图片降级为 [图片] 占位，避免请求体与 token 膨胀。"""
        ctx = Context(config)
        ctx.add_user_message("第一张图", [IMG])
        ctx.add_assistant_message("看到了")
        ctx.add_user_message("第二张图", [IMG])
        history = ctx.history
        assert history[0]["content"] == "第一张图\n[图片]"
        assert isinstance(history[2]["content"], list)
        assert history[2]["content"][1]["image_url"]["url"] == IMG

    def test_add_user_message_without_images_is_str(self, config):
        ctx = Context(config)
        ctx.add_user_message("纯文本")
        assert ctx.messages[0].content == "纯文本"
