"""智能家居抽象层测试"""

import pytest

from sump.smart_home import NoneBackend, SmartHomeBackend, from_config


@pytest.mark.asyncio
async def test_none_backend_is_empty():
    backend = NoneBackend()
    assert await backend.list_devices() == []
    assert await backend.get_state("light.1") is None
    assert await backend.set_state("light.1", "on") is False
    assert await backend.call_service("light", "turn_on") is False


def test_none_backend_implements_interface():
    assert issubclass(NoneBackend, SmartHomeBackend)


def test_from_config_defaults_to_none(config):
    backend = from_config(config)
    assert isinstance(backend, NoneBackend)


def test_from_config_explicit_none(config):
    config._data.setdefault("smart_home", {})["backend"] = "none"
    backend = from_config(config)
    assert isinstance(backend, NoneBackend)
