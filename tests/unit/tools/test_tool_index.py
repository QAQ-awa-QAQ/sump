"""工具索引测试"""

import pytest

from sump.tools.base import Tool
from sump.tools.builtin.tool_index import ToolIndexTool
from sump.tools.registry import ToolRegistry


class _Dummy(Tool):
    name = "dummy"
    description = "一个占位工具"

    async def execute(self, **kwargs):
        return "ok"


@pytest.mark.asyncio
async def test_lists_all_registered_tools():
    reg = ToolRegistry()
    reg.register(_Dummy())
    reg.register(ToolIndexTool(reg))
    result = await reg.get("list_tools").execute()
    assert "dummy" in result
    assert "list_tools" in result


@pytest.mark.asyncio
async def test_empty_registry_still_lists_self():
    reg = ToolRegistry()
    reg.register(ToolIndexTool(reg))
    result = await reg.get("list_tools").execute()
    assert "list_tools" in result


def test_schema_is_object_without_required():
    schema = ToolIndexTool(ToolRegistry()).to_openai_schema()
    assert schema["function"]["name"] == "list_tools"
    assert "required" not in schema["function"]["parameters"]
