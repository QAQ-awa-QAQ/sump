"""关键输出格式化"""


class KeyOutput:
    """格式化关键输出信息"""

    @staticmethod
    def format(action: str, detail: str, data: dict | None = None) -> str:
        """格式化关键输出"""
        lines = [f"[{action}] {detail}"]
        if data:
            for k, v in data.items():
                lines.append(f"  {k}: {v}")
        return "
".join(lines)
