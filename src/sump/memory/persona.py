"""人格/灵魂管理器（SOUL.md / AGENTS.md 注入与睡眠精简）"""

from pathlib import Path
from typing import Any


class PersonaManager:
    """加载人格 md 文件，注入为 system prompt；睡眠时精简超长文件。

    文件默认取项目根目录的 SOUL.md / AGENTS.md，不存在则跳过。
    """

    def __init__(
        self,
        files: list[str] | None = None,
        max_bytes: int = 5000,
        base_dir: str | Path = ".",
    ) -> None:
        self._files = files or ["SOUL.md", "AGENTS.md"]
        self._max_bytes = max_bytes
        self._base_dir = Path(base_dir)

    # ------------------------------------------------------------------
    # 注入
    # ------------------------------------------------------------------

    def get_system_prompt(self) -> str:
        """拼接所有文件内容，总字节超过 max_bytes 时截断。"""
        parts: list[str] = []
        total = 0
        for name in self._files:
            content = self._read(name)
            if not content:
                continue
            parts.append(content)
            total += len(content.encode("utf-8"))
            if total >= self._max_bytes:
                break
        prompt = "\n\n".join(parts)
        return self._truncate_bytes(prompt, self._max_bytes)

    # ------------------------------------------------------------------
    # 睡眠精简
    # ------------------------------------------------------------------

    async def compact(self, llm: Any) -> str:
        """对每个超长文件精简一次（不重试、不回滚），返回结果描述。"""
        reports: list[str] = []
        for name in self._files:
            path = self._base_dir / name
            if not path.exists():
                continue
            content = path.read_text(encoding="utf-8")
            if len(content.encode("utf-8")) <= self._max_bytes:
                continue
            reports.append(await self._compact_one(llm, name, path, content))
        return "；".join(reports) if reports else "无需精简"

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _read(self, name: str) -> str:
        path = self._base_dir / name
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")

    async def _compact_one(
        self, llm: Any, name: str, path: Path, original: str
    ) -> str:
        old_bytes = len(original.encode("utf-8"))
        # 精简前备份，供手动回滚（代码不做自动回滚重试）
        backup = path.with_name(name + ".bak")
        backup.write_text(original, encoding="utf-8")

        prompt = (
            f"以下是文件 {name} 的内容，长度 {old_bytes} 字节，超过上限 {self._max_bytes} 字节。\n"
            "请精简它：只删除冗余与重复，必须完整保留所有关键语义、语气和人格设定，"
            "不得新增内容、不得改变原意。\n"
            "直接输出精简后的 markdown 原文，不要任何解释、不要代码块包装。\n\n"
            f"---\n{original}\n---"
        )
        try:
            raw = await llm.chat_flash(prompt, max_tokens=4096, temperature=0.3)
        except Exception:
            return f"{name}: 精简失败"

        new = raw.strip()
        new_bytes = len(new.encode("utf-8"))
        # 未缩短或为空则弃用，原文件保持不变
        if not new or new_bytes >= old_bytes:
            return f"{name}: 弃用（未缩短）"

        path.write_text(new, encoding="utf-8")
        return f"{name}: {old_bytes}→{new_bytes} 字节"

    @staticmethod
    def _truncate_bytes(text: str, max_bytes: int) -> str:
        data = text.encode("utf-8")
        if len(data) <= max_bytes:
            return text
        return data[:max_bytes].decode("utf-8", errors="ignore")
