"""Idempotent demo clinicians (synthetic). Runs only when SEED_DEMO_USERS=true (or --force).
The prototype's admin account is deliberately NOT seeded (ADR-018: one role)."""
from __future__ import annotations

import asyncio
import sys
import uuid

from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import create_engine
from app.domain.clock import utcnow
from app.services.password_hasher import PasswordHasherService

DEMO_PASSWORD = "Nephro#2026"
DEMO_USERS = [
    ("Dr. Anita Rao", "dr.rao@nephrocare.demo"),
    ("Dr. Karan Malhotra", "dr.malhotra@nephrocare.demo"),
]
_INSERT = text(
    """INSERT INTO users (id, email, password_hash, full_name, role, created_at, updated_at)
       VALUES (:id, :email, :hash, :name, 'clinician', :now, :now)
       ON CONFLICT (email) DO NOTHING"""
)


async def main(force: bool) -> int:
    s = get_settings()
    if not (s.seed_demo_users or force):
        print("SEED_DEMO_USERS is not true; nothing seeded.")
        return 0
    hasher = PasswordHasherService(s)
    engine = create_engine(s)
    created = 0
    try:
        async with engine.begin() as conn:
            for name, email in DEMO_USERS:
                result = await conn.execute(_INSERT, {
                    "id": uuid.uuid4(), "email": email, "hash": await hasher.hash(DEMO_PASSWORD),
                    "name": name, "now": utcnow()})
                created += result.rowcount or 0
    finally:
        await engine.dispose()
    print(f"seed complete: {created} created, {len(DEMO_USERS) - created} already present")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main("--force" in sys.argv)))
