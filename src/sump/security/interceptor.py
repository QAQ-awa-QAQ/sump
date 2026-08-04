"""拦截器（规则/正则过滤）"""


class Interceptor:
    """请求/响应拦截器，基于规则过滤"""

    def __init__(self):
        self._rules: list[dict] = []

    def load_rules(self, path: str) -> None:
        """从 YAML 加载规则"""
        pass

    def check(self, content: str) -> bool:
        """检查内容是否通过拦截，True 表示放行"""
        return True
