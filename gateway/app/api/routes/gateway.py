"""The catch-all for /api and /api/** (LLD §25.2). Every request goes through GatewayPipeline."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from app.api.deps import get_pipeline
from app.core.errors import AppError, error_response
from app.services.pipeline import GatewayPipeline

router = APIRouter()
log = logging.getLogger("gateway.pipeline")
# TRACE, CONNECT and HEAD are not listed: Starlette answers 405, rendered as the METHOD_NOT_ALLOWED envelope.
METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]


@router.api_route("/api", methods=METHODS, include_in_schema=False)
@router.api_route("/api/{rest:path}", methods=METHODS, include_in_schema=False)
async def gateway(request: Request, pipeline: GatewayPipeline = Depends(get_pipeline)) -> Response:  # noqa: B008
    try:
        return await pipeline.handle(request)
    except AppError as exc:
        return error_response(exc.status_code, exc.code, exc.message, exc.details, exc.headers)
    except Exception:
        # Never let an exception escape: the response must still pass through CorsMiddleware, or the
        # browser reports a CORS failure instead of the envelope (LLD §5). Type only, never the message.
        log.exception("gateway.unhandled")
        return error_response(500, "INTERNAL_ERROR", "Something went wrong.")
