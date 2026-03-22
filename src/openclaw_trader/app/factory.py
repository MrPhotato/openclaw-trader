from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from .api import build_router
from .dependencies import ServiceContainer, build_container


def create_app(container: ServiceContainer | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if container is not None:
            app.state.container = container
        elif not hasattr(app.state, "container"):
            app.state.container = build_container()
        try:
            yield
        finally:
            if hasattr(app.state, "container"):
                app.state.container.close()

    app = FastAPI(title="openclaw-trader-v2", version="2.0.0", lifespan=lifespan)
    app.include_router(build_router())

    frontend_dist = Path(__file__).resolve().parents[3] / "frontend" / "dist"
    if frontend_dist.exists():
        @app.get("/", include_in_schema=False)
        async def frontend_index():
            return FileResponse(frontend_dist / "index.html")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def frontend_fallback(full_path: str):
            if full_path.startswith("api/") or full_path == "healthz":
                raise HTTPException(status_code=404, detail="not_found")
            target = frontend_dist / full_path
            if target.exists() and target.is_file():
                return FileResponse(target)
            return FileResponse(frontend_dist / "index.html")
    return app
