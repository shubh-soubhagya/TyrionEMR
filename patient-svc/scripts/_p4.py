from pathlib import Path


def sub(p: str, a: str, b: str) -> None:
    path = Path(p)
    s = path.read_text(encoding="utf-8")
    assert a in s, (p, a[:70])
    path.write_text(s.replace(a, b, 1), encoding="utf-8", newline="\n")


sub("app/core/config.py", "    clinic_tz: str", "    max_body_bytes: int = 1_048_576             # request bodies above this are rejected with 413\n    clinic_tz: str")

sub("app/core/common_setup.py", """from app.core.errors import install_exception_handlers""",
    """from app.core.body_limit import BodyLimitMiddleware
from app.core.errors import install_exception_handlers""")
sub("app/core/common_setup.py", "    install_exception_handlers(app)\n",
    "    install_exception_handlers(app)\n"
    "    # Innermost of the three, so a 413 still carries X-Request-ID and shows up in the access log and metrics\n"
    "    app.add_middleware(BodyLimitMiddleware)\n")

sub("app/core/logging.py", '''SENSITIVE_KEYS = frozenset({
    "password", "new_password", "token", "access_token", "refresh_token", "authorization",
    "cookie", "set-cookie", "set_cookie", "email", "secret", "api_key", "token_hash",
})''', '''SENSITIVE_KEYS = frozenset({
    # credentials
    "password", "new_password", "token", "access_token", "refresh_token", "authorization",
    "cookie", "set-cookie", "set_cookie", "email", "secret", "api_key", "token_hash",
    # patient data (PHI): a future ``extra={...}`` must not be able to leak any of it. Matched case-insensitively.
    "first_name", "last_name", "name", "full_name", "patient_name", "phone", "address", "date_of_birth", "dob",
    "mrn", "past_medical_history", "family_history", "social_history", "chief_complaint", "symptoms",
    "examination_notes", "assessment", "plan", "allergen", "reaction", "description", "q",
})''')
print("p4 wired")
