"""Request-scoped context shared by logging, errors and middleware."""
from contextvars import ContextVar

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


def get_request_id() -> str:
    return request_id_var.get()


def route_template(scope) -> str:
    """Full route template, e.g. ``/patients`` or ``/patients/{id}``.

    FastAPI reports ``route.path`` relative to the included router (``/login``), so the prefix is
    recovered from the real request path. Only the template is ever logged or used as a metric label,
    never the raw path (which may contain ids) or the query string.
    """
    route = scope.get("route")
    relative = getattr(route, "path_format", None) or getattr(route, "path", None)
    if not relative:
        return "unmatched"
    rel = relative.strip("/").split("/")
    actual = scope.get("path", "").strip("/").split("/")
    prefix = actual[: max(0, len(actual) - len(rel))]
    return "/" + "/".join([*prefix, *rel]).strip("/")
