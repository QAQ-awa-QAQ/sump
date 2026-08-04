"""鎷︽埅鍣紙瑙勫垯/姝ｅ垯杩囨护锛?""


class Interceptor:
    """璇锋眰/鍝嶅簲鎷︽埅鍣紝鍩轰簬瑙勫垯杩囨护"""

    def __init__(self):
        self._rules: list[dict] = []

    def load_rules(self, path: str) -> None:
        """浠?YAML 鍔犺浇瑙勫垯"""
        pass

    def check(self, content: str) -> bool:
        """妫€鏌ュ唴瀹规槸鍚﹂€氳繃鎷︽埅锛孴rue 琛ㄧず鏀捐"""
        return True