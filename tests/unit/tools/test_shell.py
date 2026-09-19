"""Shell 工具纯逻辑测试（描述生成 / 平台提示 / 编码检测）"""

import sys

from sump.tools.builtin.shell import (
    ShellTool,
    _auto_platform_hint,
    _build_description,
    _detect_encoding,
)


def test_build_description_windows():
    desc = _build_description("windows")
    assert "cmd/PowerShell" in desc


def test_build_description_linux():
    desc = _build_description("linux")
    assert "bash/sh" in desc


def test_build_description_custom_passthrough():
    desc = _build_description("自定义提示词")
    assert "自定义提示词" in desc


def test_auto_platform_hint_matches_platform():
    hint = _auto_platform_hint()
    if sys.platform.startswith("win"):
        assert "cmd/PowerShell" in hint
    else:
        assert "bash/sh" in hint


def test_detect_encoding_returns_str():
    assert _detect_encoding() in ("utf-8", "cp936", "gbk", "gb2312", "gb18030")


def test_shell_schema():
    schema = ShellTool().to_openai_schema()
    assert schema["function"]["name"] == "shell"
    assert "command" in schema["function"]["parameters"]["properties"]
