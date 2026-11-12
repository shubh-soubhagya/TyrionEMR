"""Route resolution (LLD §19.2). Pure."""
from __future__ import annotations

from dataclasses import dataclass

from app.routing.paths import route_template
from app.routing.table import API_PREFIX, PUBLIC_ROUTES, Route


@dataclass(frozen=True)
class RouteMatch:
    route: Route
    template: str          # '/api/labs/patients/{id}/results'
    upstream_path: str     # raw path minus '/api', e.g. '/labs/patients/0b7c…/results'
    public: bool


def resolve(method: str, raw_path: str, segments: list[str], routes: dict[str, Route]) -> RouteMatch | None:
    """None means 404. '/api/internal/**' resolves to None like any unknown prefix (§8.2)."""
    if len(segments) < 2 or segments[0] != API_PREFIX.strip("/"):
        return None
    route = routes.get(segments[1])          # whole-segment match: 'encountersX' is not 'encounters'
    if route is None:
        return None
    template = route_template(segments)
    return RouteMatch(
        route=route,
        template=template,
        upstream_path=raw_path[len(API_PREFIX):],
        # exact match only: '/api/auth/login/' (trailing slash) is not the public route (LLD 18.1)
        public=(method, template) in PUBLIC_ROUTES and not raw_path.endswith("/"),
    )
