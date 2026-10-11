"""FastAPI application factory."""

from fastapi import FastAPI

from opsagent import __version__
from opsagent.infra.logging import configure_logging
from opsagent.settings import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, json=settings.log_json)

    app = FastAPI(title="invoice-ops-agent", version=__version__)

    @app.get("/health", tags=["ops"])
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__, "environment": settings.environment}

    return app


app = create_app()
