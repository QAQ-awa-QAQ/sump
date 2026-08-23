"""深层记忆冲突检测（store / update / merge / skip）

对候选新记忆召回已有深层记忆，批量 LLM 判断四动作，避免语义重复。
"""

import json
from typing import Any

from sump.memory._llm_json import chat_flash_json


class DeepDedup:
    """深层记忆去重：召回候选 + 批量 LLM 判断 store/update/merge/skip。"""

    def __init__(self, llm: Any, deep_memory: Any, top_k_candidates: int = 3) -> None:
        self._llm = llm
        self._deep_memory = deep_memory
        self._top_k_candidates = top_k_candidates

    async def decide(self, new_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """返回每条新记忆的决策：{id, action, target_keys, merged_content}。

        解析失败或 decisions 为空时回退为全部 store（不丢记忆）。
        """
        if not new_items:
            return []

        # 1. 候选召回：每条新记忆用自身内容做混合检索
        candidates: dict[str, list[dict[str, Any]]] = {}
        for item in new_items:
            try:
                hits = await self._deep_memory.search(
                    item["content"], top_k=self._top_k_candidates
                )
            except Exception:
                hits = []
            candidates[str(item["id"])] = hits

        # 2. 批量 LLM 判断
        data = await chat_flash_json(
            self._llm,
            self._build_prompt(new_items, candidates),
            max_tokens=2048,
            temperature=0.3,
            label="deep_dedup",
        )

        decisions = (data or {}).get("decisions") or []
        if not decisions:
            return self._fallback_store_all(new_items)

        valid_actions = {"store", "update", "merge", "skip"}
        result: list[dict[str, Any]] = []
        for d in decisions:
            if not isinstance(d, dict):
                continue
            action = d.get("action", "store")
            if action not in valid_actions:
                action = "store"
            result.append({
                "id": str(d.get("id", "")),
                "action": action,
                "target_keys": d.get("target_keys", []) or [],
                "merged_content": d.get("merged_content"),
            })
        return result

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _build_prompt(
        self,
        new_items: list[dict[str, Any]],
        candidates: dict[str, list[dict[str, Any]]],
    ) -> str:
        lines = ["新记忆："]
        for item in new_items:
            lines.append(f"  id={item['id']} content={item['content']}")
        lines.append("")
        lines.append("每条新记忆的已有候选：")
        for item in new_items:
            hits = candidates.get(str(item["id"]), [])
            for h in hits:
                lines.append(f"  新id={item['id']} 候选key={h['key']} content={h['value']}")
        lines.append("")
        lines.append(
            "请判断每条新记忆与候选的关系，四选一：\n"
            "- store：全新信息，直接新增\n"
            "- skip：已有记忆更好，丢弃新记忆\n"
            "- update：新记忆更权威，覆盖旧记忆（target_keys=要删的旧 key）\n"
            "- merge：新旧互补，合并成一条（target_keys=要删的旧 key，merged_content=合并后内容）\n"
            "只输出 JSON，不要代码块、不要解释：\n"
            '{"decisions": [{"id": "新id", "action": "store", "target_keys": [], "merged_content": null}]}'
        )
        return "\n".join(lines)

    @staticmethod
    def _fallback_store_all(new_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {"id": str(item["id"]), "action": "store", "target_keys": [], "merged_content": None}
            for item in new_items
        ]

    @staticmethod
    def _parse_json(raw: str) -> dict[str, Any] | None:
        try:
            text = raw.strip().removeprefix("```json").removesuffix("```").strip()
            data = json.loads(text)
            return data if isinstance(data, dict) else None
        except (json.JSONDecodeError, AttributeError):
            return None
