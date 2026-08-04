"""SOUL.md 跷载器"""

from pathlib import Path


class SoulLoader:
    初始化并解析 SOUL.md 文件

    def __init__(self, path: str | Path = "SOUL.md"):
        self.path = Path(path)

    def load(self) -> str:
        pass
