from fastapi import FastAPI

from app.core.body_limit import BodyLimitMiddleware
from app.core.errors import install_exception_handlers
from app.core.metrics import MetricsMiddleware
from app.core.middleware import RequestContextMiddleware


def install_common_middleware(app: FastAPI) -> None:
    """Error envelope handlers, metrics, and request id + access log (outermost)."""
    install_exception_handlers(app)
    # Innermost of the three, so a 413 still carries X-Request-ID and shows up in the access log and metrics
    app.add_middleware(BodyLimitMiddleware)
    app.add_middleware(MetricsMiddleware)
    app.add_middleware(RequestContextMiddleware)
