"""Shell 命令工具（无安全检查，前端负责权限警告）"""

import asyncio
import subprocess
import sys
from typing import Any

from sump.tools.base import Tool

# 各平台提示词（告诉 LLM 当前系统可用什么命令）
_PLATFORM_PROMPTS: dict[str, str] = {
    "windows": (
        "当前系统是 Windows，只能用 cmd/PowerShell 命令（如 dir、type、findstr），"
        "不能使用 Linux 命令（ls、cat、grep 等不可用）。"
    ),
    "linux": (
        "当前系统是 Linux，只能用 bash/sh 命令（如 ls、cat、grep），"
        "不能使用 Windows 命令（dir、type、findstr 等不可用）。"
    ),
}

_TIMEOUT = 30


def _auto_platform_hint() -> str:
    """按运行时系统自动选择平台提示词。"""
    if sys.platform.startswith("win"):
        return _PLATFORM_PROMPTS["windows"]
    return _PLATFORM_PROMPTS["linux"]


def _build_description(platform: str) -> str:
    """根据 platform 配置生成工具描述；未知值视为自定义提示词原文。"""
    if platform in _PLATFORM_PROMPTS:
        hint = _PLATFORM_PROMPTS[platform]
    elif platform == "auto":
        hint = _auto_platform_hint()
    else:
        hint = platform
    return (
        "在终端执行一条命令并返回输出。"
        f"{hint}"
        "适用场景：查看文件列表、读取文件内容、运行脚本等。"
        f"注意：命令有 {_TIMEOUT} 秒超时限制。"
    )


class ShellTool(Tool):
    name = "shell"
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

    def __init__(self, platform: str = "auto") -> None:
        self.description = _build_description(platform)

    async def execute(self, command: str = "", **kwargs: Any) -> str:
        """执行命令，返回 stdout + stderr（截断至 4000 字符）。"""
        encoding = _detect_encoding()
        try:
            proc = await asyncio.to_thread(
                subprocess.run,
                command,
                shell=True,
                capture_output=True,
                timeout=_TIMEOUT,
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
