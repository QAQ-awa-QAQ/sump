"""OpenTelemetry 瀵煎嚭"""


class Tracer:
    """鍒嗗竷寮忚拷韪?""

    def __init__(self):
        self._spans: list[dict] = []

    def start_span(self, name: str) -> dict:
        span = {"name": name, "start": None, "end": None}
        self._spans.append(span)
        return span

    def end_span(self, span: dict) -> None:
        pass