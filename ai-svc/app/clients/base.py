"""Shared plumbing for the two upstream clients."""
from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, ValidationError

from app.core.context import CallContext as CallContext  # re-exported for the clients
from app.core.errors import UpstreamUnavailable
from app.core.metrics import UPSTREAM_CALLS

log = logging.getLogger("ai.clients")


def parse[M: BaseModel](model: type[M], body: Any, upstream: str) -> M:
    """A response that does not match the contract is an upstream failure, logged without the body (PHI)."""
    try:
        return model.model_validate(body)
    except ValidationError as exc:
        UPSTREAM_CALLS.labels(upstream, "bad_response").inc()
        log.error("upstream.contract_violation", extra={
            "upstream": upstream, "model": model.__name__,
            "fields": [".".join(map(str, e["loc"])) for e in exc.errors()[:5]]})
        raise UpstreamUnavailable(upstream) from None
