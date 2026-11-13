from fastapi import FastAPI

from app.core.config import Settings
from app.core.cors import CorsMiddleware
from app.core.errors import install_exception_handlers
from app.core.metrics import MetricsMiddleware
from app.core.middleware import RequestContextMiddleware
from app.core.security_headers import SecurityHeadersMiddleware


def install_common_middleware(app: FastAPI, s: Settings) -> None:
    """Error envelope handlers and the middleware stack of LLD §25.3, outermost first:
    request context (id, access log, last-resort 500) > security headers > metrics > CORS > routes.
    """
    install_exception_handlers(app)
    # add_middleware prepends: the LAST one added is the OUTERMOST.
    app.add_middleware(CorsMiddleware, allowed_origins=s.cors_allowed_origins, max_age_s=s.cors_max_age_s,
                       allow_mock_scenario=s.environment != "production")
    app.add_middleware(MetricsMiddleware)
    app.add_middleware(SecurityHeadersMiddleware, hsts=s.hsts_enabled)
    app.add_middleware(RequestContextMiddleware)
