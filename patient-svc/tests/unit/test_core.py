from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.core.dberrors import sqlstate_of
from app.core.logging import JsonFormatter
from app.domain.clock import FakeClock, today_in
from app.services.jwks import JwksCache, parse_jwks, thumbprint_kid
from tests.conftest import jwk_for, make_settings


def test_today_uses_clinic_tz_not_utc():
    # 20:00 UTC on 11 Nov is already 12 Nov 01:30 in IST (P-09)
    clock = FakeClock(datetime(2026, 11, 11, 20, 0, tzinfo=UTC))
    assert today_in(clock, "Asia/Kolkata").isoformat() == "2026-11-12"
    assert today_in(clock, "UTC").isoformat() == "2026-11-11"


def test_invalid_clinic_tz_fails_at_startup():
    with pytest.raises(ValidationError):
        make_settings(clinic_tz="Mars/Olympus")


def test_sqlstate_extraction():
    class Orig(Exception):
        sqlstate = "57014"

    class Wrapper(Exception):
        orig = Orig()

    assert sqlstate_of(Wrapper()) == "57014"


def test_log_formatter_redacts_sensitive_keys():
    import logging
    rec = logging.LogRecord("t", logging.INFO, "", 0, "evt", (), None)
    rec.authorization = "Bearer abc"
    rec.email = "a@b.c"
    out = JsonFormatter("patient-svc").format(rec)
    assert "abc" not in out and "a@b.c" not in out and "[redacted]" in out


def test_parse_jwks_rejects_bad_kid_and_small_keys(rsa_key):
    good = jwk_for(rsa_key)
    assert list(parse_jwks({"keys": [good]})) == [thumbprint_kid(rsa_key.public_key())]
    assert parse_jwks({"keys": [{**good, "kid": "forged"}]}) == {}
    assert parse_jwks({"keys": [{**good, "alg": "HS256"}]}) == {}
    with pytest.raises(ValueError):
        parse_jwks({"nope": 1})


async def test_jwks_keeps_last_good_set_on_failure(rsa_key):
    calls = {"n": 0}

    async def fetch():
        calls["n"] += 1
        if calls["n"] > 1:
            raise RuntimeError("auth-svc down")
        return {"keys": [jwk_for(rsa_key)]}

    cache = JwksCache(fetch, make_settings())
    assert await cache.refresh("t") is True
    assert await cache.refresh("t") is False
    assert cache.key_count == 1


async def test_jwks_unknown_kid_refetch_is_rate_limited(rsa_key):
    n = {"v": 0}

    async def fetch():
        n["v"] += 1
        return {"keys": [jwk_for(rsa_key)]}

    cache = JwksCache(fetch, make_settings(jwks_min_refetch_s=60.0))
    await cache.refresh("t")
    for _ in range(5):
        assert await cache.key_for("unknown") is None
    assert n["v"] <= 2          # initial fetch + at most one unknown-kid refetch


PHI_KEYS = ["first_name", "last_name", "name", "full_name", "patient_name", "phone", "address", "date_of_birth", "dob",
            "mrn", "past_medical_history", "family_history", "social_history", "chief_complaint", "symptoms",
            "examination_notes", "assessment", "plan", "allergen", "reaction", "description", "q"]


def test_log_formatter_masks_every_phi_key_including_nested_values_and_any_case():
    import logging
    rec = logging.LogRecord("t", logging.INFO, "", 0, "evt", (), None)
    rec.payload = {"outer": {k.upper() if i % 2 else k: "ZQX-SECRET" for i, k in enumerate(PHI_KEYS)},
                   "rows": [{"first_name": "ZQX-SECRET", "ok": 1}, [{"Phone": "ZQX-SECRET"}]]}
    rec.mrn = "PT-000101"                       # top-level extra
    out = JsonFormatter("patient-svc").format(rec)
    assert "ZQX-SECRET" not in out and "PT-000101" not in out
    assert '"ok":1' in out                      # non-sensitive values are untouched
