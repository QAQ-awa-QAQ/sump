"""关键输出格式化测试"""

from sump.debug.key_output import KeyOutput


def test_format_without_data():
    assert KeyOutput.format("SAVE", "已保存") == "[SAVE] 已保存"


def test_format_with_data():
    out = KeyOutput.format("EXEC", "执行", {"cmd": "ls", "ok": True})
    assert "[EXEC] 执行" in out
    assert "  cmd: ls" in out
    assert "  ok: True" in out
