"""SUMP API 服务入口"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from sump.api.routes import router


def create_app() -> FastAPI:
    app = FastAPI(title="SUMP API", version="0.1.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(router)
    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("sump.api.server:app", host="0.0.0.0", port=8765, reload=True)
