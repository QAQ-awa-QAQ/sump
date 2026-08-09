"""Shell 命令工具（无安全检查，前端负责权限警告）"""

import asyncio
import subprocess
from typing import Any

from sump.tools.base import Tool


class ShellTool(Tool):
    name = "shell"
    description = (
        "在终端执行一条命令并返回输出。"
        "适用场景：查看文件列表、读取文件内容、运行脚本等。"
        "注意：命令有 30 秒超时限制。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "要执行的 Shell 命令，例如 dir、cat file.txt",
            },
        },
        "required": ["command"],
    }

    async def execute(self, command: str, **kwargs: Any) -> str:
        """执行命令，返回 stdout + stderr（截断至 4000 字符）。"""
        encoding = _detect_encoding()
        try:
            proc = await asyncio.to_thread(
                subprocess.run,
                command,
                shell=True,
                capture_output=True,
                timeout=30,
            )
            out = proc.stdout.decode(encoding, errors="replace")
            err = proc.stderr.decode(encoding, errors="replace")
            result = out + err if err else out
            return result[:4000] if result.strip() else "(无输出)"
        except subprocess.TimeoutExpired:
            return "错误：命令执行超时（30 秒）"
        except Exception as e:
            return f"错误：{e}"


def _detect_encoding() -> str:
    """检测系统终端编码：中文 Windows → gbk，否则 utf-8。"""
    import locale
    try:
        enc = locale.getpreferredencoding()
        return enc if enc.lower() in ("cp936", "gbk", "gb2312", "gb18030") else "utf-8"
    except Exception:
        return "utf-8"
