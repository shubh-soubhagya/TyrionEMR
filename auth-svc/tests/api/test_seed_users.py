"""The demo users carry the ids patient-svc's seed expects for its encounters' clinicians (G10)."""
import uuid

import pytest

from app.cli import seed_users
from app.core.config import get_settings
from tests.conftest import TEST_DB_URL, sql

pytestmark = pytest.mark.api
NAMESPACE = uuid.UUID("9b3f6a52-7c1e-4d0b-9a58-2f4e8c1d7a10")      # patient-svc/app/domain/seed_ids.py


@pytest.fixture(autouse=True)
def cli_env(monkeypatch, migrated_db):
    monkeypatch.setenv("AUTH_DATABASE_URL", TEST_DB_URL)
    monkeypatch.setenv("ARGON2_TIME_COST", "1")
    monkeypatch.setenv("ARGON2_MEMORY_KIB", "1024")
    monkeypatch.setenv("ARGON2_PARALLELISM", "1")
    monkeypatch.setenv("ENVIRONMENT", "test")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


async def test_seeded_ids_are_the_uuid5_ids_patient_svc_uses(app):
    assert await seed_users.main(force=True) == 0
    rows = dict(await sql(app, "SELECT email, id FROM users"))
    assert set(rows) == {email for _, email in seed_users.DEMO_USERS}
    for email, uid in rows.items():
        assert uid == uuid.uuid5(NAMESPACE, "user:" + email.lower())


async def test_seeding_twice_is_idempotent_and_keeps_the_ids(app, capsys):
    await seed_users.main(force=True)
    before = await sql(app, "SELECT email, id FROM users ORDER BY email")
    assert await seed_users.main(force=True) == 0
    assert "0 created" in capsys.readouterr().out
    assert await sql(app, "SELECT email, id FROM users ORDER BY email") == before
