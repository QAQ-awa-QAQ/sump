"""鎵ц鍣ㄦ祴璇?""

import pytest

from sump.core.context import Context
from sump.core.executor import Executor


class TestExecutor:
    @pytest.mark.asyncio
    async def test_execute(self, config):
        ctx = Context(config)
        executor = Executor(ctx)
        result = await executor.execute([{"step": "test"}])
        assert isinstance(result, str)