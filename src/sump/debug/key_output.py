"""鍏抽敭杈撳嚭鏍煎紡鍖?""


class KeyOutput:
    """鏍煎紡鍖栧叧閿緭鍑轰俊鎭?""

    @staticmethod
    def format(action: str, detail: str, data: dict | None = None) -> str:
        lines = [f"[{action}] {detail}"]
        if data:
            for k, v in data.items():
                lines.append(f"  {k}: {v}")
        return "\n".join(lines)