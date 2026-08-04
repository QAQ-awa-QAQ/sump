"""LLM 客户端封装"""


class LLMClient:
    """统一的 LLM 调用接口"""

    def __init__(self, model: str = "gpt-4o", temperature: float = 0.7):
        self.model = model
        self.temperature = temperature

    async def chat(self, messages: list[dict[str, str]]) -> str:
        """发送对话请求"""
        # TODO: 接入实际 LLM API
        return ""
