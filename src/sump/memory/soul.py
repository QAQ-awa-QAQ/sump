"""SOUL.md 加载器"""

from pathlib import Path


class SoulLoader:
    """加载并解析 SOUL.md 文件"""

    def __init__(self, path: str | Path = "SOUL.md"):
        self.path = Path(path)

    def load(self) -> str:
        if self.path.exists():
            return self.path.read_text(encoding="utf-8")
        return ""
