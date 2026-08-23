"""DeepSeek V4 XML 工具调用解析测试"""

import json

from sump.core.models.deepseek import DeepSeekClient


def test_parse_xml_tool_calls():
    content = (
        "<tool_calls>"
        '<invoke name="image_vision">'
        '<parameter name="image">data\\napcat_images\\x.jpg</parameter>'
        '<parameter name="question">描述图片</parameter>'
        "</invoke>"
        "</tool_calls>"
    )
    calls = DeepSeekClient._parse_xml_tool_calls(content)
    assert calls is not None
    assert calls[0]["function"]["name"] == "image_vision"
    args = json.loads(calls[0]["function"]["arguments"])
    assert args["image"] == "data\\napcat_images\\x.jpg"
    assert args["question"] == "描述图片"


def test_parse_xml_no_tool_calls():
    assert DeepSeekClient._parse_xml_tool_calls("普通回复") is None
    assert DeepSeekClient._parse_xml_tool_calls("") is None


def test_parse_xml_multiple_invokes():
    content = (
        "<tool_calls>"
        '<invoke name="a"><parameter name="x">1</parameter></invoke>'
        '<invoke name="b"><parameter name="y">2</parameter></invoke>'
        "</tool_calls>"
    )
    calls = DeepSeekClient._parse_xml_tool_calls(content)
    assert calls is not None
    assert len(calls) == 2
    assert calls[1]["function"]["name"] == "b"
