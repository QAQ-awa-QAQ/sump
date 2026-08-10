"""OpenTelemetry 导出"""

from typing import Any


class Tracer:
    """分布式追踪"""

    def __init__(self) -> None:
        self._spans: list[dict[str, Any]] = []

    def start_span(self, name: str) -> dict[str, Any]:
        """开始一个追踪 span"""
        span: dict[str, Any] = {"name": name, "start": None, "end": None}
        self._spans.append(span)
        return span

    def end_span(self, span: dict[str, Any]) -> None:
        """结束追踪 span"""
        pass
