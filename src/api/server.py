"""SUMP API 服务入口"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from api.routes import router
from sump.core.sleep import SleepManager, get_sleep_manager
from sump.debug.logger import setup_logger
from sump.memory.embedder import Embedder
from sump.plugins.builtin.napcat_plugin import NapCatPlugin


def _warm_embedder(cache_dir: str | None) -> None:
    """后台预热 embedding 模型（首次会下载）。"""
    try:
        Embedder(cache_dir=cache_dir).preload()
    except Exception:
        pass


async def _startup_consolidate(sm: SleepManager) -> None:
    """启动时先巩固一次（后台异步，不阻塞服务；失败只记日志）。"""
    consolidation_logger = logging.getLogger("sump.consolidation")
    try:
        result = await sm.consolidate_now()
        consolidation_logger.info("启动巩固完成：%s", result)
    except Exception as exc:  # noqa: BLE001
        consolidation_logger.error("启动巩固失败：%s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """服务生命周期：启动睡眠节拍 + 预下载模型 + 启动先巩固，关闭时中断。"""
    sm = get_sleep_manager()
    setup_logger(sm.config.get("debug.log_level", "INFO"))
    log_file = sm.config.get("debug.log_file", None)
    if log_file:
        root = logging.getLogger("sump")
        path = Path(log_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        root.addHandler(logging.FileHandler(path, encoding="utf-8"))

    await sm.start()
    cache_dir = sm.config.get("memory.deep.embedding_cache", None)
    asyncio.create_task(asyncio.to_thread(_warm_embedder, cache_dir))
    # 启动先巩固（后台异步，默认关闭）
    if bool(sm.config.get("sleep.consolidate_on_startup", False)):
        asyncio.create_task(_startup_consolidate(sm))
    # NapCat QQ 适配（按配置启用）
    napcat = NapCatPlugin(sm.config)
    await napcat.start()
    yield
    await sm.stop()
    await napcat.stop()


def create_app() -> FastAPI:
    app = FastAPI(title="SUMP API", version="0.1.0", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def sleep_reflex(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """反射唤醒：请求到达即记录活动并唤醒（生理反射，非决策）。"""
        await get_sleep_manager().on_activity()
        return await call_next(request)

    app.include_router(router)

    # 前端静态文件（存在则挂载，支持 Docker 单容器部署；开发模式 vite dev 时不触发）
    frontend_dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
    if frontend_dist.is_dir():
        app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api.server:app", host="0.0.0.0", port=8765, reload=True)
