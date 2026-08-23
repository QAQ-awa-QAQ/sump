"""NapCat (QQ) 适配插件：正向 WebSocket 接入 OneBot 11。

NapCat 作为 WS 服务端，本插件作为客户端连接其正向 WS 端口：
- 收到 OneBot `message` 事件 → 驱动 Agent 处理
- 订阅 `agent.reply` 钩子 → 把回复发回 QQ

依赖 `websockets`（uvicorn[standard] 已附带）。
"""

import asyncio
import json
import logging
from typing import Any

from sump.agent import Agent
from sump.config import Config
from sump.event import AgentEvents, get_event_bus

logger = logging.getLogger("sump.napcat")


class NapCatPlugin:
    """NapCat QQ 机器人适配插件。"""

    def __init__(self, config: Config | None = None) -> None:
        self._config = config or Config()
        self._enabled = bool(self._config.get("napcat.enabled", False))
        self._ws_url = str(self._config.get("napcat.ws_url", "ws://127.0.0.1:3001"))
        self._access_token = str(self._config.get("napcat.access_token", ""))
        self._owner_id = str(self._config.get("napcat.owner_id", "") or "").strip()
        self._name = str(self._config.get("napcat.name", "星宝") or "星宝")
        self._bus = get_event_bus()
        self._agents: dict[str, Agent] = {}
        self._pending_approval: dict[str, str] = {}  # session_id -> call_id
        self._locks: dict[str, asyncio.Lock] = {}  # session_id -> 处理锁（防并发）
        self._ws: Any = None
        self._task: asyncio.Task[None] | None = None
        # 钩子：Agent 回复完成 → 发回 QQ；审批挂起/超时 → 推送主人
        self._bus.on(AgentEvents.REPLY, self._on_reply, consumer="napcat")
        self._bus.on(AgentEvents.APPROVAL_PENDING, self._on_approval_pending, consumer="napcat")
        self._bus.on(AgentEvents.APPROVAL_EXPIRED, self._on_approval_expired, consumer="napcat")

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """启动后台连接循环（幂等）。"""
        if not self._enabled:
            logger.info("napcat 插件未启用（napcat.enabled=false）")
            return
        try:
            import websockets  # noqa: F401
        except ImportError:
            logger.error("缺少 websockets 依赖，请执行：pip install websockets")
            return
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(self._run_forever())

    async def stop(self) -> None:
        """停止连接循环。"""
        if self._task is not None:
            self._task.cancel()
            self._task = None
        ws, self._ws = self._ws, None
        if ws is not None:
            try:
                await ws.close()
            except Exception:  # noqa: BLE001
                pass

    # ------------------------------------------------------------------
    # 连接循环
    # ------------------------------------------------------------------

    async def _run_forever(self) -> None:
        while True:
            try:
                await self._connect_and_serve()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.error("napcat 连接异常，5 秒后重连：%s", exc)
                await asyncio.sleep(5)

    async def _connect_and_serve(self) -> None:
        import websockets

        url = self._ws_url
        if self._access_token:
            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}access_token={self._access_token}"
        async with websockets.connect(url) as ws:
            self._ws = ws
            logger.info("napcat 已连接：%s", self._ws_url)
            async for raw in ws:
                await self._handle_raw(str(raw))
        self._ws = None

    # ------------------------------------------------------------------
    # 事件处理
    # ------------------------------------------------------------------

    async def _handle_raw(self, raw: str) -> None:
        """处理一条 WS 原始帧。"""
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return
        if data.get("post_type") == "message":
            await self._handle_message(data)

    async def _handle_message(self, data: dict[str, Any]) -> None:
        """把 OneBot 消息事件转成 Agent 会话并驱动回复。"""
        message_type = data.get("message_type", "private")
        user_id = str(data.get("user_id", ""))
        text = self._extract_text(data.get("message"))
        image_urls = self._extract_image_urls(data.get("message"))
        if image_urls:
            local_parts: list[str] = []
            for u in image_urls:
                local = await self._download_image(u) or u
                local_parts.append(local)
            img_part = " ".join(f"[图片] {p}" for p in local_parts)
            text = f"{text}\n{img_part}" if text else img_part
        if not text or not user_id:
            return

        if message_type == "group":
            group_id = str(data.get("group_id", ""))
            session_id = f"group_{group_id}"
            reply_ctx: dict[str, Any] = {"message_type": "group", "group_id": group_id}
        else:
            session_id = f"private_{user_id}"
            reply_ctx = {"message_type": "private", "user_id": user_id}

        # 私聊零信任：非主人私聊一律拒绝
        if message_type == "private" and not self._is_owner(user_id):
            logger.warning("拒绝非主人私聊：user_id=%s", user_id)
            await self._send(reply_ctx, "抱歉，你不是授权用户，已拒绝执行。")
            return

        # 审批响应（仅主人）：1=同意 / 2=拒绝
        if (
            text in ("1", "2")
            and self._is_owner(user_id)
            and session_id in self._pending_approval
        ):
            call_id = self._pending_approval.pop(session_id, None)
            if call_id:
                async with self._get_lock(session_id):
                    await self._get_agent(session_id).approve_and_continue(call_id, text == "1")
            return

        if message_type == "group":
            await self._handle_group_message(data, session_id, text, user_id)
        else:
            await self._handle_private_message(session_id, text)

    async def _handle_private_message(self, session_id: str, text: str) -> None:
        """私聊：记录并直接回复（1v1，逐条回应）。"""
        async with self._get_lock(session_id):
            await self._bus.emit(
                AgentEvents.MESSAGE_RECEIVED, session_id=session_id, content=text, source="napcat"
            )
            agent = self._get_agent(session_id)
            try:
                async for _ in agent.run_stream(text):
                    pass  # 回复通过 agent.reply 钩子发回
            except Exception as exc:  # noqa: BLE001
                logger.error("Agent 处理失败：%s", exc)

    async def _handle_group_message(
        self, data: dict[str, Any], session_id: str, text: str, user_id: str
    ) -> None:
        """群聊：记录所有消息，智能体自主决定是否说话（@ 必回，星宝加权）。"""
        async with self._get_lock(session_id):
            agent = self._get_agent(session_id)
            nickname = str((data.get("sender") or {}).get("nickname", user_id))

            # 记录会话：主人消息带标记（供记忆提炼只针对主人）
            owner_marker = str(self._config.get("memory.owner_marker", "·主人"))
            if self._is_owner(user_id):
                label = f"[{nickname}{owner_marker}]"
            else:
                label = f"[{nickname}]"
            agent.ctx.add_user_message(f"{label} {text}")

            # 2. 决定是否说话
            at_me = self._is_at_me(data)
            mentioned = self._name in text
            if not await self._should_speak(agent, text, mentioned, at_me):
                return

            # 3. 回复（基于完整群聊上下文）
            try:
                async for _ in agent.run_core():
                    pass  # 回复通过 agent.reply 钩子发回
            except Exception as exc:  # noqa: BLE001
                logger.error("Agent 处理失败：%s", exc)

    async def _should_speak(
        self, agent: Any, text: str, mentioned: bool, at_me: bool
    ) -> bool:
        """决定是否插话：@ 必回；星宝加权；其余交给 flash 判断。"""
        if at_me:
            return True
        prompt = (
            f"你是 QQ 群里的智能体「{self._name}」。群里刚有人发了一条消息，"
            "你需要决定是否回复。\n"
            f"消息：{text}\n"
            + (f"注意：这条消息提到了你的名字「{self._name}」，倾向于回复。\n" if mentioned else "")
            + "只有当消息在向你提问、求助、明确提到你、或值得你插话时才回复；"
            "普通闲聊、无指向性的群聊不要插话。只回答 yes 或 no。"
        )
        try:
            result = await agent.llm.chat_flash(prompt, max_tokens=8, temperature=0.3)
            return "yes" in result.lower()
        except Exception:  # noqa: BLE001
            return mentioned  # flash 失败：提到名字才回

    def _is_at_me(self, data: dict[str, Any]) -> bool:
        """判断消息是否 @ 了本机器人（at 段的 qq 等于 self_id）。"""
        self_id = str(data.get("self_id", ""))
        message = data.get("message")
        if not self_id or not isinstance(message, list):
            return False
        for seg in message:
            if isinstance(seg, dict) and seg.get("type") == "at":
                if str(seg.get("data", {}).get("qq", "")) == self_id:
                    return True
        return False

    async def _on_reply(self, session_id: str, content: str, **kwargs: Any) -> None:
        """钩子：Agent 回复完成 → 发回 QQ。"""
        if not content:
            return
        ctx = self._reply_ctx(session_id)
        if ctx is None:
            return
        await self._send(ctx, content)

    async def _on_approval_pending(
        self,
        session_id: str,
        call_id: str,
        command: str,
        summary: str,
        danger: str,
        **kwargs: Any,
    ) -> None:
        """钩子：审批挂起 → 推送给主人（1 同意 / 2 拒绝）。"""
        self._pending_approval[session_id] = call_id
        ctx = self._reply_ctx(session_id)
        if ctx is None:
            return
        msg = (
            "⚠️ 待审批命令：\n"
            f"命令：{command}\n"
            f"意图：{summary or '未知'}\n"
            f"危险等级：{danger or '未知'}\n"
            "回复 1 同意，2 拒绝"
        )
        await self._send(ctx, msg)

    async def _on_approval_expired(
        self, session_id: str, call_id: str, **kwargs: Any
    ) -> None:
        """钩子：审批超时 → 通知主人并继续执行。"""
        self._pending_approval.pop(session_id, None)
        ctx = self._reply_ctx(session_id)
        if ctx is not None:
            await self._send(ctx, "审批超时，已自动拒绝。")
        agent = self._get_agent(session_id)
        try:
            async with self._get_lock(session_id):
                async for _ in agent.run_core():
                    pass  # 回复通过 agent.reply 钩子发回
        except Exception as exc:  # noqa: BLE001
            logger.error("审批超时后继续执行失败：%s", exc)

    def _reply_ctx(self, session_id: str) -> dict[str, Any] | None:
        """把 session_id 转成 OneBot 回复上下文（群/私聊）。"""
        if session_id.startswith("group_"):
            return {"message_type": "group", "group_id": session_id[len("group_"):]}
        if session_id.startswith("private_"):
            return {"message_type": "private", "user_id": session_id[len("private_"):]}
        return None

    async def _send(self, ctx: dict[str, Any], content: str) -> None:
        """通过 OneBot `send_msg` 动作发送消息。"""
        if self._ws is None:
            logger.warning("napcat 未连接，丢弃回复")
            return
        try:
            await self._ws.send(json.dumps(
                {"action": "send_msg", "params": {**ctx, "message": content}},
                ensure_ascii=False,
            ))
        except Exception as exc:  # noqa: BLE001
            logger.error("发送 QQ 消息失败：%s", exc)

    # ------------------------------------------------------------------
    # 工具
    # ------------------------------------------------------------------

    def _get_agent(self, session_id: str) -> Agent:
        """每个 QQ 群/私聊一个独立 Agent 会话，避免记忆串扰。"""
        if session_id not in self._agents:
            agent = Agent(self._config)
            agent.switch_session(session_id)
            self._agents[session_id] = agent
        return self._agents[session_id]

    def _get_lock(self, session_id: str) -> asyncio.Lock:
        """每个会话一把处理锁，串行化该会话的消息处理。"""
        lock = self._locks.get(session_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[session_id] = lock
        return lock

    def _is_owner(self, user_id: str) -> bool:
        """零信任：仅主人 QQ 号可执行；未配置主人则拒绝所有人。"""
        return bool(self._owner_id) and user_id == self._owner_id

    @staticmethod
    def _extract_text(message: Any) -> str:
        """从 OneBot message 段提取纯文本。"""
        if isinstance(message, str):
            return message.strip()
        if isinstance(message, list):
            parts: list[str] = []
            for seg in message:
                if isinstance(seg, dict) and seg.get("type") == "text":
                    parts.append(str(seg.get("data", {}).get("text", "")))
            return "".join(parts).strip()
        return ""

    @staticmethod
    def _extract_image_urls(message: Any) -> list[str]:
        """从 OneBot message 段提取图片 URL。"""
        if not isinstance(message, list):
            return []
        urls: list[str] = []
        for seg in message:
            if isinstance(seg, dict) and seg.get("type") == "image":
                url = str(seg.get("data", {}).get("url", ""))
                if url:
                    urls.append(url)
        return urls

    async def _download_image(self, url: str) -> str | None:
        """下载 QQ 图片到本地文件（内网 URL 云端不可达），返回本地路径；失败返回 None。"""
        import hashlib
        import time
        from pathlib import Path

        import httpx

        img_dir = Path(str(self._config.get("napcat.image_dir", "data/napcat_images")))
        img_dir.mkdir(parents=True, exist_ok=True)
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                data = resp.content
        except Exception as exc:  # noqa: BLE001
            logger.warning("下载 QQ 图片失败：%s %s", url, exc)
            return None

        name = hashlib.md5(data).hexdigest()[:16] + _guess_image_ext(data)
        path = img_dir / name
        path.write_bytes(data)
        return str(path)


def _guess_image_ext(data: bytes) -> str:
    """按文件实际内容判断图片扩展名。"""
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data.startswith(b"GIF8"):
        return ".gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    return ".jpg"
