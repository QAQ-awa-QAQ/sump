"""OpenTelemetry 导出"""


class Tracer:
    """分布式追踪"""

    def __init__(self):
        self._spans: list[dict] = []

    def start_span(self, name: str) -> dict:
        """开始一个追踪 span"""
        span = {"name": name, "start": None, "end": None}
        self._spans.append(span)
        return span

    def end_span(self, span: dict) -> None:
        """结束追踪 span"""
        pass
