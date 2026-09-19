"""工具注册表 / 工具集 / 工具基类测试"""

from sump.tools.base import Tool
from sump.tools.registry import ToolRegistry
from sump.tools.toolset import ToolSet


class _A(Tool):
    name = "a"
    description = "工具 A"

    async def execute(self, **kwargs):
        return "a"


class _B(Tool):
    name = "b"
    description = "工具 B"

    async def execute(self, **kwargs):
        return "b"


def test_register_and_get():
    reg = ToolRegistry()
    reg.register(_A())
    assert reg.get("a") is not None
    assert reg.get("nope") is None


def test_list_all_and_remove():
    reg = ToolRegistry()
    reg.register(_A())
    reg.register(_B())
    assert [t.name for t in reg.list_all()] == ["a", "b"]
    reg.remove("a")
    assert [t.name for t in reg.list_all()] == ["b"]
    reg.remove("nope")  # 不存在时静默忽略


def test_get_schemas():
    reg = ToolRegistry()
    reg.register(_A())
    schemas = reg.get_schemas()
    assert schemas[0]["function"]["name"] == "a"


def test_to_openai_schema():
    schema = _A().to_openai_schema()
    assert schema == {
        "type": "function",
        "function": {"name": "a", "description": "工具 A", "parameters": {}},
    }


def test_toolset_enable_disable():
    reg = ToolRegistry()
    reg.register(_A())
    reg.register(_B())
    ts = ToolSet(reg)
    ts.enable("a")
    assert [t.name for t in ts.get_active()] == ["a"]
    ts.enable("b")
    assert {t.name for t in ts.get_active()} == {"a", "b"}
    ts.disable("a")
    assert [t.name for t in ts.get_active()] == ["b"]
