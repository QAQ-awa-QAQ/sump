"""记忆生命周期集成测试"""

import pytest

from sump.memory.working import WorkingMemory
from sump.memory.shallow import ShallowMemory
from sump.memory.compressor import MemoryCompressor


class TestMemoryLifecycle:
    @pytest.mark.asyncio
    async def test_compress_flow(self):
        working = WorkingMemory(max_items=10)
        shallow = ShallowMemory()
        compressor = MemoryCompressor(working, shallow)
        await compressor.compress()
