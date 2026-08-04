"""浅层长期记忆测试"""

import pytest

from sump.memory.shallow import ShallowMemory


class TestShallowMemory:
    @pytest.mark.asyncio
    async def test_init(self):
        mem = ShallowMemory()
        assert mem is not None
