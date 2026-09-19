"""配置加载器（YAML + 环境变量 + 运行时设置）"""

import os
from pathlib import Path
from typing import Any

import yaml

from sump.settings import load_settings


class Config:
    """配置管理器，支持 YAML 文件 + 环境变量覆盖 + 运行时设置叠加"""

    def __init__(self, config_dir: str | Path = "configs", env: str | None = None):
        self.config_dir = Path(config_dir)
        self.env = env or os.getenv("SUMP_ENV", "default")
        self._data: dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        # SUMP_ENV 支持逗号分隔多环境（如 "docker,local"）：依次叠加，后者覆盖前者
        env_names = [
            name.strip() for name in str(self.env).split(",") if name.strip()
        ]
        for name in dict.fromkeys(("default", *env_names)):
            path = self.config_dir / f"{name}.yaml"
            if path.exists():
                with open(path, encoding="utf-8") as f:
                    self._deep_merge(self._data, yaml.safe_load(f) or {})
        # 运行时设置（设置中心写入 data/settings.json）优先级最高
        self._deep_merge(self._data, load_settings())

    def _deep_merge(self, base: dict[str, Any], override: dict[str, Any]) -> None:
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
                node = node.get(k)  # type: ignore[assignment]
            else:
                return default
        return node if node is not None else default

    def __getitem__(self, key: str) -> Any:
        result = self.get(key)
        if result is None:
            raise KeyError(key)
        return result
