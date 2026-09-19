"""定时等待器测试"""

import asyncio

import pytest

from sump.tools.builtin.wait import WaitTool


@pytest.mark.asyncio
async def test_wait_sleeps_for_seconds(monkeypatch):
    slept: list[int] = []

    async def fake_sleep(seconds: int) -> None:
        slept.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    w = WaitTool(max_seconds=600)
    result = await w.execute(seconds=5)
    assert result == "已等待 5 秒"
    assert slept == [5]


@pytest.mark.asyncio
async def test_seconds_clamped_to_max(monkeypatch):
    slept: list[int] = []

    async def fake_sleep(seconds: int) -> None:
        slept.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    w = WaitTool(max_seconds=600)
    result = await w.execute(seconds=9999)
    assert result == "已等待 600 秒"
    assert slept == [600]


@pytest.mark.asyncio
async def test_invalid_seconds_falls_back_to_one(monkeypatch):
    slept: list[int] = []

    async def fake_sleep(seconds: int) -> None:
        slept.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    w = WaitTool(max_seconds=600)
    result = await w.execute(seconds="abc")
    assert result == "已等待 1 秒"
    assert slept == [1]


def test_schema_has_seconds():
    schema = WaitTool().to_openai_schema()
    assert schema["function"]["name"] == "wait"
    assert "seconds" in schema["function"]["parameters"]["properties"]
