"""睡眠管理器（生理机制，非智能体决策）

睡眠像人的昼夜节律一样自动推进：
- 生物钟（睡眠时段）+ 疲劳（空闲时长）→ 自动入睡
- 浅睡持续一段时间 → 自动进入深睡
- 深睡中触发记忆整理（工具调用）
- 外部刺激（用户请求）→ 反射式唤醒，任何一步都不经 LLM

状态变化通过事件总线广播并记账，插件可订阅留钩子。
"""

import asyncio
import time
from datetime import datetime, time as dtime
from enum import Enum

from sump.config import Config
from sump.event import SleepEvents, get_event_bus
from sump.tools.builtin.memory_consolidation import MemoryConsolidationTool


class SleepState(str, Enum):
    """睡眠状态。"""

    AWAKE = "awake"
    LIGHT = "light"
    DEEP = "deep"


class SleepManager:
    """睡眠生理状态机。

    由时钟 + 空闲时长自动推进，不依赖 LLM / Planner。
    对外暴露：
    - start()/stop(): 启动/停止后台生理节拍循环
    - on_activity(): 记录本体调用并反射唤醒
    - bus: 事件总线（sleep.enter / sleep.deepen / sleep.wake / sleep.consolidate.*）
    """

    def __init__(self, config: Config | None = None) -> None:
        self.config = config or Config()
        self.bus = get_event_bus()
        self.state = SleepState.AWAKE

        # 生理节律参数
        self._enabled = bool(self.config.get("sleep.enabled", True))
        self._idle_seconds = int(self.config.get("sleep.idle_minutes", 30)) * 60
        self._deepen_after = float(self.config.get("sleep.deepen_after_seconds", 300))
        self._tick_interval = float(self.config.get("sleep.tick_interval_seconds", 10))
        self._window_start, self._window_end = self._parse_window()

        # 内部状态
        self._last_activity = time.monotonic()
        self._entered_light_at: float | None = None
        self._consolidated = False
        self._tick_task: asyncio.Task[None] | None = None
        self._consolidate_task: asyncio.Task[None] | None = None
        self._tool = MemoryConsolidationTool()

    # ------------------------------------------------------------------
    # 对外接口
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """启动后台生理节拍循环。"""
        if self._tick_task is not None:
            return
        self._tick_task = asyncio.create_task(self._tick_loop())

    async def stop(self) -> None:
        """停止后台循环并中断整理。"""
        if self._tick_task is not None:
            self._tick_task.cancel()
            self._tick_task = None
        self._interrupt_consolidation()

    async def on_activity(self) -> None:
        """记录一次本体调用并反射式唤醒（生理反射，非决策）。"""
        self._last_activity = time.monotonic()
        if self.state != SleepState.AWAKE:
            await self._wake(reason="activity")

    # ------------------------------------------------------------------
    # 生理节拍
    # ------------------------------------------------------------------

    async def tick(self) -> None:
        """推进一次睡眠状态（纯时钟 + 空闲判定）。"""
        if not self._enabled:
            return
        now = time.monotonic()
        if self.state == SleepState.AWAKE:
            if self._in_window() and (now - self._last_activity) >= self._idle_seconds:
                await self._enter_light()
        elif not self._in_window():
            await self._wake(reason="window_end")
        elif self.state == SleepState.LIGHT:
            if (
                self._entered_light_at is not None
                and (now - self._entered_light_at) >= self._deepen_after
            ):
                await self._enter_deep()

    async def _tick_loop(self) -> None:
        while True:
            await asyncio.sleep(self._tick_interval)
            await self.tick()

    # ------------------------------------------------------------------
    # 状态迁移
    # ------------------------------------------------------------------

    async def _enter_light(self) -> None:
        self._entered_light_at = time.monotonic()
        self._set_state(SleepState.LIGHT)
        await self.bus.emit(SleepEvents.ENTER, state=SleepState.LIGHT)

    async def _enter_deep(self) -> None:
        self._consolidated = False
        self._set_state(SleepState.DEEP)
        await self.bus.emit(SleepEvents.DEEPEN, state=SleepState.DEEP)
        self._start_consolidation()

    async def _wake(self, reason: str) -> None:
        previous = self.state
        if self.state == SleepState.DEEP:
            self._interrupt_consolidation()
        self._entered_light_at = None
        self._consolidated = False
        self._set_state(SleepState.AWAKE)
        await self.bus.emit(SleepEvents.WAKE, reason=reason, previous=previous)

    def _set_state(self, state: SleepState) -> None:
        self.state = state

    # ------------------------------------------------------------------
    # 记忆整理（工具调用）
    # ------------------------------------------------------------------

    def _start_consolidation(self) -> None:
        if self._consolidate_task is not None and not self._consolidate_task.done():
            return
        self._consolidate_task = asyncio.create_task(self._run_consolidation())

    def _interrupt_consolidation(self) -> None:
        """协作式中断整理任务（唤醒时避免卡顿）。"""
        if self._consolidate_task is not None and not self._consolidate_task.done():
            self._consolidate_task.cancel()
        self._consolidate_task = None

    async def _run_consolidation(self) -> None:
        await self.bus.emit(SleepEvents.CONSOLIDATE_START)
        try:
            result = await self._tool.execute()
            self._consolidated = True
            await self.bus.emit(SleepEvents.CONSOLIDATE_DONE, result=result)
        except asyncio.CancelledError:
            await self.bus.emit(SleepEvents.CONSOLIDATE_INTERRUPTED)
            raise

    # ------------------------------------------------------------------
    # 时间窗口
    # ------------------------------------------------------------------

    def _parse_window(self) -> tuple[dtime, dtime]:
        raw = self.config.get("sleep.window", ["02:00", "07:00"])
        start_s, end_s = str(raw[0]), str(raw[1])
        start = datetime.strptime(start_s, "%H:%M").time()
        end = datetime.strptime(end_s, "%H:%M").time()
        return start, end

    def _in_window(self) -> bool:
        now = datetime.now().time()
        if self._window_start <= self._window_end:
            return self._window_start <= now <= self._window_end
        return now >= self._window_start or now <= self._window_end


_singleton: SleepManager | None = None


def get_sleep_manager() -> SleepManager:
    """获取全局睡眠管理器单例。"""
    global _singleton
    if _singleton is None:
        _singleton = SleepManager()
    return _singleton
