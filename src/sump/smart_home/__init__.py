"""智能家居控制（可插拔后端）。"""

from sump.config import Config
from sump.smart_home.base import Device, SmartHomeBackend, State
from sump.smart_home.none import NoneBackend

__all__ = ["Device", "State", "SmartHomeBackend", "NoneBackend", "from_config"]


def from_config(config: Config) -> SmartHomeBackend:
    """按配置创建智能家居后端。当前仅 none 占位；未来按 backend 分发到各适配器。"""
    backend = str(config.get("smart_home.backend", "none"))
    if backend == "none":
        return NoneBackend()
    # 未来：ha -> HAAdapter(config)；mqtt -> MQTTAdapter(config)；mihome / tuya 同理
    return NoneBackend()
