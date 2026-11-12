"""Request-scoped context shared by logging, errors and middleware.

The route label used by the access log and metrics is NOT derived from the path here (deviation D4).
The pipeline (or a gateway-owned route, or CorsMiddleware) writes it to ``scope["state"]["route"]``;
anything that never sets one is ``unmatched``. Only a template is ever logged, never a raw path.
"""
from collections.abc import MutableMapping
from contextvars import ContextVar
from typing import Any

from starlette.datastructures import Headers

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

ROUTE_KEY = "route"
UNMATCHED = "unmatched"


def get_request_id() -> str:
    return request_id_var.get()


def set_route(scope: MutableMapping[str, Any], label: str) -> None:
    """Record the route label for this request (a template or a literal gateway-owned route)."""
    scope.setdefault("state", {})[ROUTE_KEY] = label


def get_route(scope: MutableMapping[str, Any]) -> str:
    state = scope.get("state")
    label = state.get(ROUTE_KEY) if isinstance(state, dict) else None
    return label if isinstance(label, str) and label else UNMATCHED


def client_ip(scope: MutableMapping[str, Any], trust_hops: int) -> str:
    """Client address for rate limits, logs and X-Forwarded-For (LLD §25.1, R13).

    Default (0 hops): the socket peer, which a client cannot spoof. Behind N trusted load balancers the
    address is taken N hops from the right of X-Forwarded-For, so a client-supplied prefix is ignored.
    """
    peer = scope["client"][0] if scope.get("client") else "unknown"
    if trust_hops <= 0:
        return str(peer)
    chain = [p.strip() for p in Headers(scope=scope).get("x-forwarded-for", "").split(",") if p.strip()]
    chain.append(str(peer))
    return chain[-(trust_hops + 1)] if len(chain) > trust_hops else chain[0]
