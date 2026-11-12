"""Rate-limit policies (LLD §9.1, §18.2). They match on the shape of the path, never on raw ids."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.core.config import Settings


@dataclass(frozen=True)
class Policy:
    name: str
    key: Literal["ip", "user"]
    per_min: int
    burst: int


def ip_policies(method: str, template: str, s: Settings) -> list[Policy]:
    out = [Policy("ip_global", "ip", s.rl_ip_global_per_min, s.rl_ip_global_burst)]
    if method == "POST" and template in ("/api/auth/login", "/api/auth/signup"):
        out.append(Policy("auth_login", "ip", s.rl_auth_login_per_min, s.rl_auth_login_burst))
    elif method == "POST" and template == "/api/auth/refresh":
        out.append(Policy("auth_refresh", "ip", s.rl_auth_refresh_per_min, s.rl_auth_refresh_burst))
    return out


def user_policies(method: str, template: str, s: Settings) -> list[Policy]:
    if method == "POST" and template == "/api/ai/patients/{id}/summary":
        return [Policy("ai_generate", "user", s.rl_ai_generate_per_min, s.rl_ai_generate_burst)]
    if method == "GET" and template == "/api/ai/summaries/{id}":
        return [Policy("ai_poll", "user", s.rl_ai_poll_per_min, s.rl_ai_poll_burst)]   # replaces user_default
    return [Policy("user_default", "user", s.rl_user_default_per_min, s.rl_user_default_burst)]
