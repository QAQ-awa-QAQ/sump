"""鐭湡璁板繂娴嬭瘯"""

import pytest

from sump.memory.working import WorkingMemory


class TestWorkingMemory:
    @pytest.mark.asyncio
    async def test_store_retrieve(self):
        mem = WorkingMemory()
        await mem.store("key1", "value1")
        result = await mem.retrieve("key1")
        assert result == "value1"

    @pytest.mark.asyncio
    async def test_forget(self):
        mem = WorkingMemory()
        await mem.store("key1", "value1")
        await mem.forget("key1")
        result = await mem.retrieve("key1")
        assert result is None

    @pytest.mark.asyncio
    async def test_lru_eviction(self):
        mem = WorkingMemory(max_items=3)
        for i in range(5):
            await mem.store(f"key{i}", f"value{i}")
        assert await mem.retrieve("key0") is None
        assert await mem.retrieve("key4") == "value4"