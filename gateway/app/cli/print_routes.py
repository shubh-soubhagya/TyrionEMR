"""Print the route table, public routes and rate-limit policies (embedded in the README, handy in reviews).

    python -m app.cli.print_routes
"""
from __future__ import annotations

from app.core.config import Settings
from app.routing.policies import ip_policies, user_policies
from app.routing.table import PUBLIC_ROUTES, build_routes


def render(s: Settings) -> str:
    lines = ["Route table (the gateway strips /api and nothing else)", "",
             f"{'/api/<prefix>':<18}{'upstream':<10}{'timeout':>8}{'body limit':>12}  cookies"]
    for prefix, r in build_routes(s).items():
        cookies = "forwarded + Set-Cookie passed" if r.forward_cookies else "dropped"
        lines.append(f"/api/{prefix:<13}{r.upstream:<10}{r.timeout_s:>7g}s{r.max_body_bytes:>11}B  {cookies}")
    lines += ["", "Public routes (no JWT at the gateway)"]
    lines += [f"  {method:<5}{path}" for method, path in sorted(PUBLIC_ROUTES, key=lambda x: x[1])]
    lines += ["", "Rate-limit policies"]
    seen: dict[str, str] = {}
    for method, template in [("GET", "/api/patients"), ("POST", "/api/auth/login"), ("POST", "/api/auth/refresh"),
                             ("POST", "/api/ai/patients/{id}/summary"), ("GET", "/api/ai/summaries/{id}")]:
        for p in [*ip_policies(method, template, s), *user_policies(method, template, s)]:
            seen.setdefault(p.name, f"{p.key:<5}{p.per_min:>5}/min  burst {p.burst}")
    lines += [f"  {name:<14}{detail}" for name, detail in seen.items()]
    return "\n".join(lines)


def main() -> None:
    print(render(Settings()))  # noqa: T201 - this CLI exists to print


if __name__ == "__main__":
    main()
