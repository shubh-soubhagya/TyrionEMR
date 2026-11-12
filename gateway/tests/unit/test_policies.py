from app.core.config import Settings
from app.routing.policies import ip_policies, user_policies

S = Settings(_env_file=None)


def names(ps):
    return [p.name for p in ps]


def test_every_request_gets_ip_global():
    assert names(ip_policies("GET", "/api/patients", S)) == ["ip_global"]


def test_login_and_signup_get_the_strict_ip_bucket():
    assert names(ip_policies("POST", "/api/auth/login", S)) == ["ip_global", "auth_login"]
    assert names(ip_policies("POST", "/api/auth/signup", S)) == ["ip_global", "auth_login"]
    login = ip_policies("POST", "/api/auth/login", S)[1]
    assert (login.per_min, login.burst, login.key) == (10, 5, "ip")


def test_refresh_is_moderate():
    p = ip_policies("POST", "/api/auth/refresh", S)[1]
    assert (p.name, p.per_min, p.burst) == ("auth_refresh", 60, 20)


def test_method_matters():
    assert names(ip_policies("GET", "/api/auth/login", S)) == ["ip_global"]


def test_default_user_policy():
    assert names(user_policies("GET", "/api/patients", S)) == ["user_default"]


def test_ai_poll_replaces_user_default_so_polling_never_eats_the_general_budget():
    assert names(user_policies("GET", "/api/ai/summaries/{id}", S)) == ["ai_poll"]
    assert names(user_policies("POST", "/api/ai/patients/{id}/summary", S)) == ["ai_generate"]
    gen = user_policies("POST", "/api/ai/patients/{id}/summary", S)[0]
    assert (gen.per_min, gen.burst, gen.key) == (10, 3, "user")


def test_values_follow_settings():
    s = Settings(_env_file=None, rl_user_default_per_min=7, rl_user_default_burst=2)
    p = user_policies("GET", "/api/labs/x", s)[0]
    assert (p.per_min, p.burst) == (7, 2)
