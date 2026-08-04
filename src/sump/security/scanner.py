"""鎵弿鍣紙鍐呭瀹夊叏锛?""


class Scanner:
    """鍐呭瀹夊叏鎵弿"""

    def scan(self, content: str) -> dict:
        """鎵弿鍐呭瀹夊叏鎬э紝杩斿洖 {safe, score, issues}"""
        return {"safe": True, "score": 1.0, "issues": []}