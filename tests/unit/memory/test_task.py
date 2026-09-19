"""任务记忆测试（会话级 store/retrieve/forget/clear + 便签）"""

import pytest

from sump.memory.task import TaskMemory


@pytest.mark.asyncio
async def test_store_and_retrieve():
    tm = TaskMemory()
    await tm.store("k", {"a": 1})
    assert await tm.retrieve("k") == {"a": 1}


@pytest.mark.asyncio
async def test_retrieve_missing_returns_none():
    tm = TaskMemory()
    assert await tm.retrieve("nope") is None


@pytest.mark.asyncio
async def test_forget():
    tm = TaskMemory()
    await tm.store("k", 1)
    await tm.forget("k")
    assert await tm.retrieve("k") is None


@pytest.mark.asyncio
async def test_clear():
    tm = TaskMemory()
    await tm.store("k", 1)
    tm.set_scratchpad("s", 2)
    await tm.clear()
    assert await tm.retrieve("k") is None
    assert tm.get_scratchpad("s") is None


def test_scratchpad():
    tm = TaskMemory()
    tm.set_scratchpad("s", 42)
    assert tm.get_scratchpad("s") == 42
    assert tm.get_scratchpad("nope") is None
