import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.container import DatasetMissing, build_container
from app.core.config import Settings, get_settings
from app.mcp.http import create_mcp_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.startup_error = None
        try:
            app.state.container = await asyncio.to_thread(build_container, settings)
        except DatasetMissing as exc:
            # Keep the process up so /api/health explains what is wrong instead of a bare crash.
            log.error("%s", exc)
            app.state.container, app.state.startup_error = None, str(exc)
        yield
        if app.state.container:
            app.state.container.close()

    app = FastAPI(title="TRACE", version="1.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Mcp-Session-Id"],
    )
    app.include_router(router)
    if settings.mcp_enabled:
        app.include_router(create_mcp_router(settings))
    return app


app = create_app()
