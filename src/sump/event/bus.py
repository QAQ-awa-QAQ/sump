"""事件总线（广播 + 记账，生理机制）

系统级事件通过总线广播，并 append-only 落库：
- event_log：事件按时间戳存档（暂不删除）
- event_consumption：谁获取（消费）了事件，追加消费标签

生产者-消费者思想：emit 方是生产者，订阅方是消费者；
全程自动记账，不经任何智能体决策。
"""

import inspect
import logging
from collections import defaultdict
from collections.abc import Callable
from typing import Any

from sump.config import Config
from sump.event.journal import EventJournal

logger = logging.getLogger("sump.events")


class EventBus:
    """广播 + 记账的事件总线。

    订阅方通过 on() 注册（consumer 为消费标识），
    生产者通过 emit() 广播；每次广播先存档事件，再逐个通知订阅者并追加消费标签。
    """

    def __init__(self, db_path: str = "data/event.db") -> None:
        self._subscribers: dict[str, list[tuple[str, Callable[..., Any]]]] = defaultdict(list)
        self._journal = EventJournal(db_path)

    def on(
        self, event: str, callback: Callable[..., Any], *, consumer: str | None = None
    ) -> None:
        """订阅事件。consumer 缺省时取回调函数名。"""
        name = consumer or getattr(callback, "__name__", repr(callback))
        self._subscribers[event].append((name, callback))

    async def emit(self, event: str, **kwargs: Any) -> list[Any]:
        """广播事件并记账：先存档事件，再逐个通知订阅者并追加消费标签。

        单个订阅者异常不中断广播，其余订阅者照常收到事件。
        """
        event_id = self._journal.record_event(event, kwargs)
        results: list[Any] = []
        for consumer, callback in self._subscribers.get(event, []):
            status = "ok"
            try:
                result = callback(**kwargs)
                if inspect.isawaitable(result):
                    result = await result
                results.append(result)
            except Exception as e:  # noqa: BLE001
                status = "error"
                logger.warning("事件 %s 的订阅者 %s 处理失败: %s", event, consumer, e)
            finally:
                self._journal.mark_consumed(event_id, consumer, status)
        return results


_singleton: EventBus | None = None


def get_event_bus() -> EventBus:
    """获取全局事件总线单例。"""
    global _singleton
    if _singleton is None:
        cfg = Config()
        db_path = str(cfg.get("events.db_path", "data/event.db"))
        _singleton = EventBus(db_path)
    return _singleton
