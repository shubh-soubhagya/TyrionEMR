from fastapi import FastAPI

from app.core.errors import install_exception_handlers
from app.core.metrics import MetricsMiddleware
from app.core.middleware import RequestContextMiddleware


def install_common_middleware(app: FastAPI) -> None:
    """Error envelope handlers, metrics, and request id + access log (outermost).

    Phase 6 adds SecurityHeadersMiddleware and CorsMiddleware in the order fixed by LLD section 25.
    """
    install_exception_handlers(app)
    app.add_middleware(MetricsMiddleware)
    app.add_middleware(RequestContextMiddleware)
