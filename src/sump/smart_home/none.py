"""占位后端：未接入任何智能家居时的空实现。"""

from typing import Any

from sump.smart_home.base import Device, SmartHomeBackend, State


class NoneBackend(SmartHomeBackend):
    """空实现，所有操作返回空/False，供未接入时占位。"""

    async def list_devices(self) -> list[Device]:
        return []

    async def get_state(self, device_id: str) -> State | None:
        return None

    async def set_state(self, device_id: str, value: Any) -> bool:
        return False

    async def call_service(
        self, domain: str, service: str, data: dict[str, Any] | None = None
    ) -> bool:
        return False
