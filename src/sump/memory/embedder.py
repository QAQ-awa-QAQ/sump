"""本地文本向量化（fastembed + bge-small-zh-v1.5）

进程内只加载一次模型，零外部 API 依赖，适合离线长期运行。
"""

import threading
from typing import Any

import numpy as np


class Embedder:
    """本地 embedding 封装，模型懒加载且进程内共享一份。"""

    _model: Any = None
    _model_lock = threading.Lock()

    def __init__(
        self,
        model_name: str = "BAAI/bge-small-zh-v1.5",
        cache_dir: str | None = None,
    ) -> None:
        self._model_name = model_name
        self._cache_dir = cache_dir

    def embed(self, texts: list[str]) -> list[list[float]]:
        """把文本列表转成向量列表。"""
        if not texts:
            return []
        model = self._load_model()
        result: list[list[float]] = []
        for v in model.embed(texts):
            arr = np.asarray(v, dtype=np.float32)
            result.append([float(x) for x in arr])
        return result

    def preload(self) -> None:
        """预热：主动加载模型（首次会联网下载，之后离线可用）。"""
        self._load_model()

    def _load_model(self) -> Any:
        """懒加载模型，进程内只加载一次。"""
        if Embedder._model is None:
            with Embedder._model_lock:
                if Embedder._model is None:
                    from fastembed import TextEmbedding

                    kwargs: dict[str, Any] = {"model_name": self._model_name}
                    if self._cache_dir:
                        kwargs["cache_dir"] = self._cache_dir
                    Embedder._model = TextEmbedding(**kwargs)
        return Embedder._model


def cosine_scores(query_embedding: list[float], matrix: np.ndarray) -> np.ndarray:
    """批量余弦相似度：query (d,) 与 matrix (n, d) → 分数 (n,)。"""
    q = np.asarray(query_embedding, dtype=np.float32)
    q_norm = float(np.linalg.norm(q))
    denom = np.linalg.norm(matrix, axis=1) * q_norm
    denom[denom == 0] = 1e-12
    return (matrix @ q) / denom
