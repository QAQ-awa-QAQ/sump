"""全局运行时设置（data/settings.json，优先级高于 yaml / 环境变量）

设置中心通过 API 写入本文件；Config 加载时叠加（最高优先级）。
配置项由 CONFIG_SCHEMA 声明（key / 类型 / 分组 / 是否敏感 / 是否需重启），
API 按 schema 校验并保留类型（bool / int / float 不再被 str() 破坏）。
"""

import json
import os
from pathlib import Path
from typing import Any

# ---- 配置项 schema ----
# type: string / secret / int / float / bool / enum / list
# restart: True 表示保存后需重启进程生效（仅 deepseek 段可热更新）
# enum 类型需提供 options
CONFIG_SCHEMA: list[dict[str, Any]] = [
    # ---- Agent ----
    {"key": "agent.name", "label": "名称", "type": "string", "section": "agent", "default": "SUMP", "hint": "Agent 显示名", "restart": True},
    {"key": "agent.max_rounds", "label": "最大工具轮次", "type": "int", "section": "agent", "default": 10, "hint": "单次对话工具调用最大轮次", "restart": True},
    {"key": "agent.context_window", "label": "上下文窗口", "type": "int", "section": "agent", "default": 50, "hint": "上下文消息条数", "restart": True},
    {"key": "agent.inject_reasoning", "label": "注入推理内容", "type": "bool", "section": "agent", "default": False, "hint": "恢复历史会话时是否注入思考过程", "restart": True},
    {"key": "agent.tool_hint_every", "label": "工具提示注入轮次", "type": "int", "section": "agent", "default": 7, "hint": "每几轮重新注入工具提示（0=禁用）", "restart": True},

    # ---- 模型 ----
    {"key": "deepseek.api_key", "label": "API Key", "type": "secret", "section": "deepseek", "default": "", "hint": "留空表示不修改", "restart": False},
    {"key": "deepseek.base_url", "label": "Base URL", "type": "string", "section": "deepseek", "default": "https://api.deepseek.com", "restart": False},
    {"key": "deepseek.model", "label": "主对话模型", "type": "string", "section": "deepseek", "default": "deepseek-flash", "hint": "全局默认（QQ 等场景）", "restart": False},
    {"key": "deepseek.vision_model", "label": "视觉模型", "type": "string", "section": "deepseek", "default": "deepseek-flash", "restart": False},
    {"key": "deepseek.flash_model", "label": "轻量任务模型", "type": "string", "section": "deepseek", "default": "deepseek-flash", "hint": "标题总结 / 记忆提炼 / 安全分析等高频调用", "restart": False},
    {"key": "deepseek.reasoning_effort", "label": "思考强度", "type": "enum", "section": "deepseek", "default": "high", "options": ["low", "high", "max"], "hint": "仅思考模式开启时生效", "restart": True},
    {"key": "deepseek.thinking_enabled", "label": "思考模式", "type": "bool", "section": "deepseek", "default": False, "restart": True},
    {"key": "deepseek.max_tokens", "label": "最大输出 token", "type": "int", "section": "deepseek", "default": 4096, "restart": True},
    {"key": "deepseek.temperature", "label": "温度", "type": "float", "section": "deepseek", "default": 1.0, "hint": "仅在非思考模式生效", "restart": True},
    {"key": "deepseek.max_retries", "label": "最大重试次数", "type": "int", "section": "deepseek", "default": 3, "restart": True},
    {"key": "deepseek.retry_delay", "label": "重试间隔（秒）", "type": "float", "section": "deepseek", "default": 1.0, "hint": "指数退避", "restart": True},

    # ---- 记忆 ----
    {"key": "memory.owner_marker", "label": "主人标记", "type": "string", "section": "memory", "default": "·主人", "hint": "记忆只提炼带此标记的消息", "restart": True},
    {"key": "memory.working.backend", "label": "工作记忆后端", "type": "enum", "section": "memory", "default": "disk", "options": ["memory", "disk"], "restart": True},
    {"key": "memory.working.max_bytes", "label": "工作记忆容量（字节）", "type": "int", "section": "memory", "default": 102400, "restart": True},
    {"key": "memory.session.max_episodes", "label": "会话最大条数", "type": "int", "section": "memory", "default": 10000, "restart": True},
    {"key": "memory.shallow.priority_threshold", "label": "浅层丢弃阈值", "type": "int", "section": "memory", "default": 60, "hint": "低于此分不写入", "restart": True},
    {"key": "memory.deep.priority_threshold", "label": "深层升级阈值", "type": "int", "section": "memory", "default": 70, "hint": "低于此分不升级", "restart": True},
    {"key": "memory.deep.inject_count", "label": "核心强制注入条数", "type": "int", "section": "memory", "default": 5, "restart": True},
    {"key": "memory.deep.top_k", "label": "深层召回条数", "type": "int", "section": "memory", "default": 10, "restart": True},
    {"key": "memory.retention_days", "label": "记忆保留天数", "type": "int", "section": "memory", "default": 365, "hint": "小于 3 禁用回收", "restart": True},
    {"key": "memory.max_shallow_entries", "label": "浅层条数上限", "type": "int", "section": "memory", "default": 2000, "restart": True},
    {"key": "memory.max_deep_entries", "label": "深层条数上限", "type": "int", "section": "memory", "default": 50, "restart": True},
    {"key": "memory.recall.max_results", "label": "召回注入条数上限", "type": "int", "section": "memory", "default": 5, "restart": True},
    {"key": "memory.recall.max_chars", "label": "召回字符预算", "type": "int", "section": "memory", "default": 800, "restart": True},
    {"key": "memory.recall.core_max_chars", "label": "核心注入字符预算", "type": "int", "section": "memory", "default": 400, "restart": True},
    {"key": "memory.recall.timeout", "label": "召回超时（秒）", "type": "float", "section": "memory", "default": 3.0, "restart": True},
    {"key": "memory.soul.max_bytes", "label": "灵魂注入字节上限", "type": "int", "section": "memory", "default": 5000, "restart": True},

    # ---- 工具 ----
    {"key": "tools.builtin.shell.enabled", "label": "Shell 工具", "type": "bool", "section": "tools", "default": True, "restart": True},
    {"key": "tools.builtin.shell.timeout", "label": "Shell 超时（秒）", "type": "int", "section": "tools", "default": 30, "restart": True},
    {"key": "tools.builtin.shell.platform", "label": "Shell 平台", "type": "enum", "section": "tools", "default": "auto", "options": ["windows", "linux", "auto"], "restart": True},
    {"key": "tools.builtin.file.enabled", "label": "文件工具", "type": "bool", "section": "tools", "default": True, "restart": True},
    {"key": "tools.builtin.search.enabled", "label": "搜索工具", "type": "bool", "section": "tools", "default": True, "restart": True},
    {"key": "tools.builtin.web.enabled", "label": "网页工具", "type": "bool", "section": "tools", "default": True, "restart": True},
    {"key": "tools.builtin.web.timeout", "label": "网页超时（秒）", "type": "int", "section": "tools", "default": 10, "restart": True},
    {"key": "tools.builtin.datetime.enabled", "label": "日期时间工具", "type": "bool", "section": "tools", "default": True, "restart": True},
    {"key": "tools.builtin.wait.max_seconds", "label": "等待上限（秒）", "type": "int", "section": "tools", "default": 600, "hint": "定时等待器的最大等待秒数", "restart": True},
    {"key": "tools.mcp.enabled", "label": "MCP 工具", "type": "bool", "section": "tools", "default": False, "hint": "Model Context Protocol 工具接入", "restart": True},

    # ---- 技能 ----
    {"key": "skills.auto_create", "label": "自动创建技能", "type": "bool", "section": "skills", "default": True, "restart": True},
    {"key": "skills.proficiency_threshold", "label": "熟练度阈值", "type": "float", "section": "skills", "default": 0.7, "restart": True},

    # ---- 评估 ----
    {"key": "evaluation.enabled", "label": "启用内部评估", "type": "bool", "section": "evaluation", "default": True, "restart": True},
    {"key": "evaluation.finish_threshold", "label": "完成阈值", "type": "float", "section": "evaluation", "default": 0.8, "hint": "评分达到视为完成", "restart": True},
    {"key": "evaluation.retry_threshold", "label": "重试阈值", "type": "float", "section": "evaluation", "default": 0.5, "hint": "评分低于视为需重试", "restart": True},

    # ---- 安全 ----
    {"key": "security.interceptor.enabled", "label": "拦截器", "type": "bool", "section": "security", "default": True, "restart": True},
    {"key": "security.scanner.enabled", "label": "扫描器", "type": "bool", "section": "security", "default": True, "restart": True},
    {"key": "security.judge.enabled", "label": "审判官", "type": "bool", "section": "security", "default": True, "restart": True},
    {"key": "security.judge.threshold", "label": "审批阈值", "type": "float", "section": "security", "default": 0.5, "restart": True},
    {"key": "security.notify_safe", "label": "安全命令也通知", "type": "bool", "section": "security", "default": True, "restart": True},
    {"key": "security.approval_timeout", "label": "审批超时（秒）", "type": "int", "section": "security", "default": 30, "hint": "超时自动拒绝", "restart": True},

    # ---- 调试 ----
    {"key": "debug.log_level", "label": "日志级别", "type": "enum", "section": "debug", "default": "INFO", "options": ["DEBUG", "INFO", "WARNING", "ERROR"], "restart": True},
    {"key": "debug.trace_enabled", "label": "链路追踪", "type": "bool", "section": "debug", "default": False, "restart": True},
    {"key": "debug.key_output_enabled", "label": "关键输出", "type": "bool", "section": "debug", "default": True, "restart": True},

    # ---- 睡眠 ----
    {"key": "sleep.enabled", "label": "启用睡眠机制", "type": "bool", "section": "sleep", "default": True, "restart": True},
    {"key": "sleep.consolidate_on_startup", "label": "启动即巩固", "type": "bool", "section": "sleep", "default": False, "restart": True},
    {"key": "sleep.idle_minutes", "label": "空闲分钟阈值", "type": "int", "section": "sleep", "default": 30, "restart": True},
    {"key": "sleep.deepen_after_seconds", "label": "浅睡转深睡（秒）", "type": "int", "section": "sleep", "default": 300, "restart": True},
    {"key": "sleep.tick_interval_seconds", "label": "节拍检查间隔（秒）", "type": "int", "section": "sleep", "default": 10, "restart": True},

    # ---- NapCat ----
    {"key": "napcat.enabled", "label": "启用 NapCat QQ", "type": "bool", "section": "napcat", "default": True, "restart": True},
    {"key": "napcat.ws_url", "label": "WebSocket 地址", "type": "string", "section": "napcat", "default": "ws://127.0.0.1:3000", "restart": True},
    {"key": "napcat.access_token", "label": "访问令牌", "type": "secret", "section": "napcat", "default": "", "hint": "留空表示不修改", "restart": True},
    {"key": "napcat.owner_id", "label": "主人 QQ 号", "type": "secret", "section": "napcat", "default": "", "hint": "零信任：仅主人可执行", "restart": True},
    {"key": "napcat.name", "label": "机器人名字", "type": "string", "section": "napcat", "default": "星宝", "hint": "群聊提到该名字增加权重", "restart": True},
    {"key": "napcat.image_retention_days", "label": "图片保留天数", "type": "int", "section": "napcat", "default": 7, "restart": True},

    # ---- 智能家居 ----
    {"key": "smart_home.backend", "label": "后端", "type": "enum", "section": "smart_home", "default": "none", "options": ["none", "ha", "mqtt"], "hint": "none / Home Assistant / MQTT", "restart": True},
    {"key": "smart_home.ha.url", "label": "HA 地址", "type": "string", "section": "smart_home", "default": "http://127.0.0.1:8123", "restart": True},
    {"key": "smart_home.ha.token", "label": "HA 令牌", "type": "secret", "section": "smart_home", "default": "", "hint": "留空表示不修改", "restart": True},
    {"key": "smart_home.mqtt.host", "label": "MQTT 主机", "type": "string", "section": "smart_home", "default": "127.0.0.1", "restart": True},
    {"key": "smart_home.mqtt.port", "label": "MQTT 端口", "type": "int", "section": "smart_home", "default": 1883, "restart": True},
]

# 分组显示名（按出现顺序）
_SECTION_LABELS: dict[str, str] = {
    "agent": "Agent",
    "deepseek": "模型",
    "memory": "记忆",
    "tools": "工具",
    "skills": "技能",
    "evaluation": "评估",
    "security": "安全",
    "debug": "调试",
    "sleep": "睡眠",
    "napcat": "NapCat QQ",
    "smart_home": "智能家居",
}


def settings_path() -> Path:
    """设置文件路径（可用 SUMP_SETTINGS_FILE 环境变量覆盖，测试用）。"""
    return Path(os.getenv("SUMP_SETTINGS_FILE", "data/settings.json"))


def schema_map() -> dict[str, dict[str, Any]]:
    """key -> schema 项。"""
    return {item["key"]: item for item in CONFIG_SCHEMA}


def load_settings() -> dict[str, Any]:
    """读取设置文件（嵌套结构，与 yaml 同构）；不存在或损坏时返回空字典。"""
    path = settings_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _coerce(item: dict[str, Any], raw: Any) -> Any:
    """按 schema 类型转换值，保留 bool / int / float / list 类型。"""
    typ = item["type"]
    if typ == "bool":
        if isinstance(raw, bool):
            return raw
        return str(raw).strip().lower() in ("1", "true", "yes", "on")
    if typ == "int":
        return int(float(raw))
    if typ == "float":
        return float(raw)
    if typ == "list":
        if isinstance(raw, list):
            return raw
        return [s.strip() for s in str(raw).split(",") if s.strip()]
    return str(raw)  # string / secret / enum


def _nested_to_flat(nested: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    """嵌套字典 → 扁平 key（点号分隔）。"""
    flat: dict[str, Any] = {}
    for k, v in nested.items():
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            flat.update(_nested_to_flat(v, key))
        else:
            flat[key] = v
    return flat


def _flat_to_nested(flat: dict[str, Any]) -> dict[str, Any]:
    """扁平 key → 嵌套字典。"""
    nested: dict[str, Any] = {}
    for key, value in flat.items():
        parts = key.split(".")
        node = nested
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value
    return nested


def sanitize_patch(patch: dict[str, Any]) -> dict[str, Any]:
    """按 schema 校验扁平 patch：只保留已知 key，按类型转换。"""
    smap = schema_map()
    clean: dict[str, Any] = {}
    for key, raw in patch.items():
        item = smap.get(key)
        if item is None:
            continue
        if item["type"] == "secret" and not str(raw).strip():
            continue  # 敏感字段空值视为"不修改"
        try:
            clean[key] = _coerce(item, raw)
        except (ValueError, TypeError):
            continue
    return clean


def save_settings(patch: dict[str, Any]) -> dict[str, Any]:
    """合并保存扁平 patch（校验 + 类型转换），返回保存后的完整扁平设置。"""
    merged_flat = _nested_to_flat(load_settings())
    merged_flat.update(sanitize_patch(patch))
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_flat_to_nested(merged_flat), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return merged_flat


def mask_secret(value: str) -> str:
    """打码敏感值：保留首 6 尾 4（短值整体打码）。"""
    if not value:
        return ""
    if len(value) <= 12:
        return "••••••••"
    return f"{value[:6]}••••{value[-4:]}"
