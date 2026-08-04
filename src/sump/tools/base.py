"""Tool 抽象基类"""

from abc import ABC, abstractmethod
from typing import Any


class Tool(ABC):
    """所有工具的抽象基类"""

    name: str = ""
    description: str = ""
    parameters: dict = {}

    @abstractmethod
    async def execute(self, **kwargs) -> Any:
        """执行工具"""

    def to_openai_schema(self) -> dict:
        """转换为 OpenAI function-calling 格式"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }
