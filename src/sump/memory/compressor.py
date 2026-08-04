"""短期到浅层压缩器"""

from sump.memory.working import WorkingMemory
from sump.memory.shallow import ShallowMemory


class MemoryCompressor:
    """将短期记忆压缩到浅层长期记忆"""

    def __init__(self, working: WorkingMemory, shallow: ShallowMemory):
        self.working = working
        self.shallow = shallow

    async def compress(self) -> None:
        """执行压缩"""
        pass
