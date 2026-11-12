"""Application factory. Later phases add build_state() (clients, JWKS cache, rate limiter, pipeline), the
lifespan and the remaining routes."""
from __future__ import annotations

from fastapi import FastAPI

from app.api.routes import health
from app.core.common_setup import install_common_middleware
from app.core.config import Settings, get_settings
from app.core.guard import enforce_production
from app.core.logging import configure_logging


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    enforce_production(settings)          # refuse to start on an unsafe production configuration (D3)
    configure_logging(settings.service_name, settings.log_level)
    app = FastAPI(title="gateway", version="1.0.0", docs_url=None, redoc_url=None, openapi_url=None,
                  redirect_slashes=False)
    app.state.settings = settings
    install_common_middleware(app)
    app.include_router(health.router)
    return app


app = create_app()
