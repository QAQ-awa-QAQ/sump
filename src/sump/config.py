"""配置加载器（YAML + 环境变量）"""

import os
from pathlib import Path
from typing import Any

import yaml


class Config:
    """配置管理器，支持 YAML 文件 + 环境变量覆盖"""

    def __init__(self, config_dir: str | Path = "configs", env: str | None = None):
        self.config_dir = Path(config_dir)
        self.env = env or os.getenv("SUMP_ENV", "default")
        self._data: dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        for name in ("default", self.env):
            path = self.config_dir / f"{name}.yaml"
            if path.exists():
                with open(path, encoding="utf-8") as f:
                    self._deep_merge(self._data, yaml.safe_load(f) or {})

    def _deep_merge(self, base: dict, override: dict) -> None:
        for key, value in override.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                self._deep_merge(base[key], value)
            else:
                base[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        keys = key.split(".")
        node = self._data
        for k in keys:
            if isinstance(node, dict):
                node = node.get(k)
            else:
                return default
        return node if node is not None else default

    def __getitem__(self, key: str) -> Any:
        result = self.get(key)
        if result is None:
            raise KeyError(key)
        return result
