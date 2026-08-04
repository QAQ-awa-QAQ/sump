"""工具集管理"""

from sump.tools.base import Tool
from sump.tools.registry import ToolRegistry


class ToolSet:
    """管理一组工具的生命周期"""

    def __init__(self, registry: ToolRegistry):
        self.registry = registry
        self._active: set[str] = set()

    def enable(self, name: str) -> None:
        """启用工具"""
        self._active.add(name)

    def disable(self, name: str) -> None:
        """禁用工具"""
        self._active.discard(name)

    def get_active(self) -> list[Tool]:
        """获取当前激活的工具列表"""
        return [t for name, t in self.registry._tools.items() if name in self._active]
