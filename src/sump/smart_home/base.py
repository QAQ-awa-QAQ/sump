"""智能家居控制抽象层。

SUMP 只依赖 SmartHomeBackend 接口，底层后端可插拔：
- HAAdapter: Home Assistant（REST/WebSocket，跑在 7×24 主机）
- MQTTAdapter: 局域网 MQTT 总线（mosquitto 跑在 OpenWrt）
- MiHomeAdapter / TuyaAdapter: 厂商云 API
- NoneBackend: 占位实现（尚未接入任何后端时）
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Device:
    """智能家居设备描述。"""

    id: str                           # 唯一标识（HA entity_id / MQTT topic 等）
    name: str = ""                    # 显示名（如"客厅灯"）
    domain: str = ""                  # 领域（light / switch / climate ...）
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass
class State:
    """设备当前状态。"""

    device_id: str
    state: Any = None                 # 状态值（on/off、温度数值等）
    available: bool = True            # 是否在线可达
    attributes: dict[str, Any] = field(default_factory=dict)


class SmartHomeBackend(ABC):
    """智能家居后端抽象接口（HA/MQTT/米家/涂鸦均实现此接口）。"""

    @abstractmethod
    async def list_devices(self) -> list[Device]:
        """枚举所有设备。"""

    @abstractmethod
    async def get_state(self, device_id: str) -> State | None:
        """读取设备状态，设备不存在返回 None。"""

    @abstractmethod
    async def set_state(self, device_id: str, value: Any) -> bool:
        """设置设备状态（开灯/调温等），返回是否成功。"""

    @abstractmethod
    async def call_service(
        self, domain: str, service: str, data: dict[str, Any] | None = None
    ) -> bool:
        """调用领域服务（场景/自动化），返回是否成功。"""
