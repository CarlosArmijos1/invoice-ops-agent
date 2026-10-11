"""FastAPI application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException

from opsagent import __version__
from opsagent.api.routes import invoices, operations
from opsagent.container import Container, build_container
from opsagent.infra.logging import configure_logging, get_logger
from opsagent.settings import REPO_ROOT, Settings, get_settings

log = get_logger(__name__)
FRONTEND_DIST = REPO_ROOT / "frontend" / "dist"


class SPAStaticFiles(StaticFiles):
    """Serve the React build; unknown non-API paths fall back to index.html (client routing)."""

    async def get_response(self, path: str, scope: Any) -> Any:
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code == 404 and not path.startswith("api"):
                return FileResponse(Path(str(self.directory)) / "index.html")
            raise


def create_app(settings: Settings | None = None, container: Container | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, json=settings.log_json)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        owned = container is None
        app.state.container = container or build_container(settings)
        if settings.bootstrap_demo:
            from opsagent.bootstrap import bootstrap_demo

            bootstrap_demo(app.state.container)
        scheduler = None
        if settings.scheduler_enabled:
            from opsagent.scheduler.jobs import build_scheduler

            scheduler = build_scheduler(app.state.container)
            scheduler.start()
            log.info("scheduler_started_in_process")
        yield
        if scheduler is not None:
            scheduler.shutdown(wait=False)
        if owned:
            app.state.container.close()

    app = FastAPI(
        title="invoice-ops-agent",
        version=__version__,
        description="Agente autónomo de cuentas por pagar: extrae, concilia y decide.",
        lifespan=lifespan,
    )
    if container is not None:
        app.state.container = container
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health", tags=["ops"])
    def health(request: Request) -> JSONResponse:
        body: dict[str, Any] = {
            "status": "ok",
            "version": __version__,
            "environment": settings.environment,
            "llm_mode": settings.llm_mode,
            "scheduler": settings.scheduler_enabled,
        }
        current: Container | None = getattr(request.app.state, "container", None)
        if current is not None:
            try:
                with current.session_factory() as session:
                    session.execute(text("SELECT 1"))
                body["database"] = "ok"
            except Exception as exc:
                body |= {"status": "degraded", "database": type(exc).__name__}
                return JSONResponse(body, status_code=503)
        return JSONResponse(body)

    app.include_router(invoices.router)
    app.include_router(operations.router)
    if FRONTEND_DIST.is_dir():
        app.mount("/", SPAStaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
    return app
