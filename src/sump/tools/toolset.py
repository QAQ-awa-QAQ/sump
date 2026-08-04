"""宸ュ叿闆嗙鐞?""

from sump.tools.base import Tool
from sump.tools.registry import ToolRegistry


class ToolSet:
    """绠＄悊涓€缁勫伐鍏风殑鐢熷懡鍛ㄦ湡"""

    def __init__(self, registry: ToolRegistry):
        self.registry = registry
        self._active: set[str] = set()

    def enable(self, name: str) -> None:
        self._active.add(name)

    def disable(self, name: str) -> None:
        self._active.discard(name)

    def get_active(self) -> list[Tool]:
        return [t for name, t in self.registry._tools.items() if name in self._active]