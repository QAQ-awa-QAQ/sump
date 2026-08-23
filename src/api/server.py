"""SUMP API 服务入口"""

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from api.routes import router
from sump.core.sleep import get_sleep_manager
from sump.memory.embedder import Embedder


def _warm_embedder(cache_dir: str | None) -> None:
    """后台预热 embedding 模型（首次会下载）。"""
    try:
        Embedder(cache_dir=cache_dir).preload()
    except Exception:
        pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    """服务生命周期：启动睡眠生理节拍 + 后台预下载模型，关闭时中断。"""
    await get_sleep_manager().start()
    cache_dir = get_sleep_manager().config.get("memory.deep.embedding_cache", None)
    asyncio.create_task(asyncio.to_thread(_warm_embedder, cache_dir))
    yield
    await get_sleep_manager().stop()


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
    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api.server:app", host="0.0.0.0", port=8765, reload=True)
