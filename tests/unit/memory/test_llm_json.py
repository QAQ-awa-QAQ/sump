"""LLM JSON 解析辅助测试（容错解析 + 重试语义）"""

import pytest

from sump.memory._llm_json import chat_flash_json, parse_json


def test_parse_plain_json():
    assert parse_json('{"a": 1}') == {"a": 1}


def test_parse_json_with_fence():
    assert parse_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_parse_invalid_returns_none():
    assert parse_json("not json") is None


def test_parse_non_dict_returns_none():
    assert parse_json("[1, 2, 3]") is None


@pytest.mark.asyncio
async def test_chat_flash_json_success():
    class FakeLLM:
        async def chat_flash(self, prompt, **kwargs):
            return '{"ok": true}'

    assert await chat_flash_json(FakeLLM(), "p") == {"ok": True}


@pytest.mark.asyncio
async def test_chat_flash_json_retries_on_bad_json():
    calls: list[int] = []

    class FakeLLM:
        async def chat_flash(self, prompt, **kwargs):
            calls.append(1)
            return "not json" if len(calls) == 1 else '{"ok": true}'

    result = await chat_flash_json(FakeLLM(), "p", max_retries=3)
    assert result == {"ok": True}
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_chat_flash_json_gives_up_after_retries():
    class FakeLLM:
        async def chat_flash(self, prompt, **kwargs):
            return "not json"

    assert await chat_flash_json(FakeLLM(), "p", max_retries=2) is None


@pytest.mark.asyncio
async def test_chat_flash_json_handles_call_exception():
    class FakeLLM:
        async def chat_flash(self, prompt, **kwargs):
            raise RuntimeError("boom")

    assert await chat_flash_json(FakeLLM(), "p", max_retries=2) is None
