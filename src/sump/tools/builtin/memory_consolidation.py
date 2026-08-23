"""记忆整理工具（睡眠中由生理机制调用）"""

from typing import Any

from sump.config import Config
from sump.memory.archive import ArchiveMemory
from sump.memory.deep import DeepMemory
from sump.memory.persona import PersonaManager
from sump.memory.scene import SceneMemory
from sump.memory.session_memory import SessionMemory
from sump.memory.shallow import ShallowMemory
from sump.tools.base import Tool
from sump.tools.builtin.deep_extraction import DeepExtractionTool
from sump.tools.builtin.scene_aggregation import SceneAggregationTool
from sump.tools.builtin.shallow_extraction import ShallowExtractionTool


class MemoryConsolidationTool(Tool):
    """记忆整理工具。

    由睡眠生理机制直接调用，不经 LLM 决策（生理机制，非智能体主动决策）。
    流程：会话消息 → 浅层记忆提炼 → 浅层升级深层 → 归档副本 → 从会话记忆清除。
    """

    name = "memory_consolidation"
    description = "整理长期记忆：会话提炼归档、浅层升级深层、修剪过期信息"
    parameters = {
        "type": "object",
        "properties": {},
    }

    def __init__(self, config: Config, llm: Any, deep_embedder: Any = None) -> None:
        self._llm = llm
        self._session_memory = SessionMemory(
            config.get("memory.session.db_path", "data/session.db")
        )
        self._shallow_memory = ShallowMemory(
            config.get("memory.shallow.db_path", "data/shallow.db")
        )
        self._deep_memory = DeepMemory(
            config.get("memory.deep.db_path", "data/deep.db"),
            embedder=deep_embedder,
            embedder_cache_dir=config.get("memory.deep.embedding_cache", None),
        )
        self._archive = ArchiveMemory(
            config.get("memory.archive.db_path", "data/archive.db")
        )
        self._scene_memory = SceneMemory(
            config.get("memory.scene.db_path", "data/scene.db")
        )
        self._extractor = ShallowExtractionTool(
            llm, self._shallow_memory,
            priority_threshold=int(config.get("memory.shallow.priority_threshold", 60)),
        )
        self._deep_extractor = DeepExtractionTool(
            llm, self._shallow_memory, self._deep_memory,
            priority_threshold=int(config.get("memory.deep.priority_threshold", 70)),
        )
        self._scene_aggregator = SceneAggregationTool(
            llm, self._shallow_memory, self._scene_memory
        )
        self._retention_days = int(config.get("memory.retention_days", 365))
        self._persona = PersonaManager(
            files=config.get("memory.soul.files", None),
            max_bytes=int(config.get("memory.soul.max_bytes", 5000)),
        )

    async def execute(self, **kwargs: Any) -> str:
        """执行记忆整理：会话提炼归档 + 浅层升级深层。"""
        sessions = self._session_memory.list_sessions()

        archived_sessions = 0
        archived_msgs = 0
        reports: list[str] = []

        for s in sessions:
            sid = str(s["id"])
            name = str(s.get("name", sid))
            messages = self._session_memory.load_all_messages(sid)
            if not messages:
                continue

            # 1. 提炼 → 浅层记忆
            extract_report = await self._extractor.execute(
                session_id=sid, messages=messages
            )

            # 2. 归档副本
            archived_msgs += self._archive.archive_session(sid, name, messages)

            # 3. 从会话记忆清除（智能体本体不可见）
            self._session_memory.delete_session(sid)

            archived_sessions += 1
            reports.append(f"{name}: {extract_report}")

        # 4. 场景聚合（浅层 → L2 场景块）
        scene_report = await self._scene_aggregator.execute()

        # 5. 浅层 → 深层升级
        deep_report = await self._deep_extractor.execute()

        # 6. 过期回收（80% 安全阈值防误删）
        shallow_expired = self._shallow_memory.delete_expired(self._retention_days)
        deep_expired = await self._deep_memory.delete_expired(self._retention_days)
        scene_expired = self._scene_memory.delete_expired(self._retention_days)
        retention_report = (
            f"浅层删 {shallow_expired} 条，深层删 {deep_expired} 条，场景删 {scene_expired} 条"
        )

        # 7. 灵魂/人格文件精简
        persona_report = await self._persona.compact(self._llm)

        parts: list[str] = []
        if archived_sessions:
            parts.append(
                f"归档 {archived_sessions} 个会话（{archived_msgs} 条消息）"
                f" | {'；'.join(reports)}"
            )
        parts.append(f"场景聚合：{scene_report}")
        parts.append(f"浅层→深层：{deep_report}")
        parts.append(f"过期回收：{retention_report}")
        parts.append(f"灵魂精简：{persona_report}")
        return "记忆整理完成：" + " | ".join(parts)
