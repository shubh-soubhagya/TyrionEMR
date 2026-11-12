"""One database per service (HLD 5.1, LLD B18.8): the ai_svc role cannot reach any other service's database."""
from __future__ import annotations

import os

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

pytestmark = pytest.mark.api


@pytest.mark.parametrize("other", ["nephro_auth_db", "nephro_lab_db", "nephro_patient_db"])
async def test_ai_svc_cannot_connect_to_other_databases(migrated_db, other):
    url = os.environ["AI_TEST_DATABASE_URL"].rsplit("/", 1)[0] + "/" + other
    engine = create_async_engine(url)
    try:
        with pytest.raises(Exception) as e:
            async with engine.connect() as c:
                await c.execute(text("SELECT 1"))
        assert "permission denied" in str(e.value).lower() or "not allowed" in str(e.value).lower()
    finally:
        await engine.dispose()


async def test_role_is_not_a_superuser_and_owns_only_its_databases(migrated_db):
    engine = create_async_engine(migrated_db)
    async with engine.connect() as c:
        row = (await c.execute(text("SELECT rolsuper, rolcreatedb, rolcreaterole FROM pg_roles WHERE rolname = current_user"))).one()
    await engine.dispose()
    assert tuple(row) == (False, False, False)
