"""娴呭眰闀挎湡璁板繂娴嬭瘯"""

import pytest

from sump.memory.shallow import ShallowMemory


class TestShallowMemory:
    @pytest.mark.asyncio
    async def test_init(self):
        mem = ShallowMemory()
        assert mem is not None