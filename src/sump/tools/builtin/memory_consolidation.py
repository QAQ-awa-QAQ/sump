"""记忆整理工具（睡眠中由生理机制调用）"""

from typing import Any

from sump.config import Config
from sump.memory.archive import ArchiveMemory
from sump.memory.conflict import ConflictResolver
from sump.memory.deep import DeepMemory
from sump.memory.persona import PersonaManager
from sump.memory.scene import SceneMemory
from sump.memory.session_memory import SessionMemory
from sump.memory.shallow import ShallowMemory
from sump.memory.state import ConsolidationState
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
            config.get("memory.shallow.db_path", "data/shallow.db"),
            embedder=deep_embedder,
            embedder_cache_dir=config.get("memory.deep.embedding_cache", None),
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
            config.get("memory.scene.db_path", "data/scene.db"),
            embedder=deep_embedder,
            embedder_cache_dir=config.get("memory.deep.embedding_cache", None),
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
        self._conflict_resolver = ConflictResolver(llm, self._deep_memory)
        self._state = ConsolidationState(
            config.get("memory.state.db_path", "data/state.db")
        )
        self._retention_days = int(config.get("memory.retention_days", 365))
        self._max_shallow = int(config.get("memory.max_shallow_entries", 2000))
        self._max_deep = int(config.get("memory.max_deep_entries", 1000))
        self._persona = PersonaManager(
            files=config.get("memory.soul.files", None),
            max_bytes=int(config.get("memory.soul.max_bytes", 5000)),
        )

    async def execute(self, **kwargs: Any) -> str:
        """执行记忆整理（纯增量）：只处理上次之后新增的数据。"""
        archived_sessions = 0
        archived_msgs = 0
        reports: list[str] = []

        # 1. 会话 → 浅层（增量：只处理新消息）
        msg_cursor = self._state.get("session_msg_id", 0)
        new_messages = self._session_memory.load_messages_since(msg_cursor)
        if new_messages:
            by_session: dict[str, list[dict[str, Any]]] = {}
            for m in new_messages:
                by_session.setdefault(str(m["session_id"]), []).append(m)
            for sid, msgs in by_session.items():
                name = self._session_memory.get_session_name(sid) or sid[:8]
                extract_report = await self._extractor.execute(
                    session_id=sid, messages=msgs
                )
                archived_msgs += self._archive.archive_session(sid, name, msgs)
                self._session_memory.delete_session(sid)
                archived_sessions += 1
                reports.append(f"{name}: {extract_report}")
            self._state.set("session_msg_id", max(m["id"] for m in new_messages))

        # 2. 场景聚合 + 浅层 → 深层（增量：只处理新浅层）
        shallow_cursor = self._state.get("shallow_id", 0)
        new_entries = self._shallow_memory.list_entries_since(shallow_cursor)
        if new_entries:
            scene_report = await self._scene_aggregator.execute(entries=new_entries)
            deep_report = await self._deep_extractor.execute(entries=new_entries)
            self._state.set("shallow_id", max(e["id"] for e in new_entries))
        else:
            scene_report = "无新浅层记忆"
            deep_report = "无新浅层记忆"

        # 3. 深层记忆矛盾检测
        conflict_report = await self._conflict_resolver.resolve()

        # 4. 容量保底：超上限时 LLM 压缩丢低价值
        overflow_report = await self._compress_overflow()

        # 5. 过期回收（80% 安全阈值 + 遗忘曲线）
        shallow_expired = self._shallow_memory.delete_expired(self._retention_days)
        deep_expired = await self._deep_memory.delete_expired(self._retention_days)
        scene_expired = self._scene_memory.delete_expired(self._retention_days)
        retention_report = (
            f"浅层删 {shallow_expired} 条，深层删 {deep_expired} 条，场景删 {scene_expired} 条"
        )

        # 6. 灵魂/人格文件精简
        persona_report = await self._persona.compact(self._llm)

        parts: list[str] = []
        if archived_sessions:
            parts.append(
                f"归档 {archived_sessions} 个会话（{archived_msgs} 条消息）"
                f" | {'；'.join(reports)}"
            )
        parts.append(f"场景聚合：{scene_report}")
        parts.append(f"浅层→深层：{deep_report}")
        parts.append(f"矛盾检测：{conflict_report}")
        parts.append(f"容量保底：{overflow_report}")
        parts.append(f"过期回收：{retention_report}")
        parts.append(f"灵魂精简：{persona_report}")
        return "记忆整理完成：" + " | ".join(parts)

    async def _compress_overflow(self) -> str:
        """浅层/深层超上限时 LLM 压缩丢低价值（保底，遗忘曲线是主机制）。"""
        reports: list[str] = []
        shallow = self._shallow_memory.list_all_entries()
        if len(shallow) > self._max_shallow:
            dropped = await self._llm_drop_low_value(shallow, self._max_shallow, "shallow")
            reports.append(f"浅层丢 {dropped} 条")
        deep = self._deep_memory.list_all()
        if len(deep) > self._max_deep:
            dropped = await self._llm_drop_low_value(deep, self._max_deep, "deep")
            reports.append(f"深层丢 {dropped} 条")
        return "；".join(reports) if reports else "无需压缩"

    async def _llm_drop_low_value(
        self, entries: list[dict[str, Any]], max_entries: int, kind: str
    ) -> int:
        """超限时：取最差的 2 倍溢出候选，让 flash 标记可丢弃的，再删除。"""
        overflow = len(entries) - max_entries
        candidates = sorted(
            entries,
            key=lambda e: (e.get("priority", 0), -e.get("access_count", 0)),
        )[: overflow * 2]

        id_key = "id" if kind == "shallow" else "key"
        lines = [
            f"{id_key}={e.get(id_key)} priority={e.get('priority', 0)} 内容={e.get('content', e.get('value', ''))}"
            for e in candidates
        ]
        prompt = (
            f"以下 {kind} 记忆已超过容量上限，请标记哪些是低价值、可以安全丢弃的。\n"
            "只依据内容与 priority 判断，保留重要的。\n"
            "只输出 JSON：{\"drop\": [\"条目id或key\"]}\n\n" + "\n".join(lines)
        )
        try:
            raw = await self._llm.chat_flash(prompt, max_tokens=512, temperature=0.3)
        except Exception:
            return 0

        import json as _json
        try:
            text = raw.strip().removeprefix("```json").removesuffix("```").strip()
            data = _json.loads(text)
        except Exception:
            return 0

        drop_ids = {str(x) for x in data.get("drop", [])}
        dropped = 0
        for e in candidates:
            if str(e.get(id_key)) in drop_ids:
                if kind == "shallow":
                    self._shallow_memory.remove_entry(int(e["id"]))
                else:
                    await self._deep_memory.forget(str(e["key"]))
                dropped += 1
        return dropped
