"""事件名常量（事件广场统一命名，避免魔法字符串散落）"""


class SleepEvents:
    """睡眠生理事件。"""

    ENTER = "sleep.enter"
    DEEPEN = "sleep.deepen"
    WAKE = "sleep.wake"
    CONSOLIDATE_START = "sleep.consolidate.start"
    CONSOLIDATE_DONE = "sleep.consolidate.done"
    CONSOLIDATE_INTERRUPTED = "sleep.consolidate.interrupted"
