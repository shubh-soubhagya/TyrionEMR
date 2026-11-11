"""Invite path for when public signup is off: create a clinician from the CLI.
Usage: python -m app.cli.create_user --email dr.x@clinic.example --name "Dr. X"
The password is prompted twice with no echo and checked against the same policy as signup."""
from __future__ import annotations

import argparse
import asyncio
import getpass
import sys
import uuid

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.core.config import get_settings
from app.db.session import create_engine
from app.domain.clock import utcnow
from app.domain.password_policy import check_password, load_common_passwords
from app.schemas.auth import _normalize_email
from app.services.password_hasher import PasswordHasherService

_INSERT = text(
    """INSERT INTO users (id, email, password_hash, full_name, role, created_at, updated_at)
       VALUES (:id, :email, :hash, :name, 'clinician', :now, :now)"""
)


async def main(email: str, name: str) -> int:
    s = get_settings()
    email = _normalize_email(email)
    if not 2 <= len(name.strip()) <= 120:
        print("Name must be 2-120 characters.", file=sys.stderr)
        return 2
    pw = getpass.getpass("Password: ")
    if pw != getpass.getpass("Repeat password: "):
        print("Passwords do not match.", file=sys.stderr)
        return 2
    violations = check_password(pw, email, load_common_passwords())
    if violations:
        for v in violations:
            print(f"- {v.message}", file=sys.stderr)
        return 2
    hashed = await PasswordHasherService(s).hash(pw)
    engine = create_engine(s)
    try:
        async with engine.begin() as conn:
            await conn.execute(_INSERT, {"id": uuid.uuid4(), "email": email, "hash": hashed,
                                         "name": name.strip(), "now": utcnow()})
    except IntegrityError:
        print("An account with this email already exists.", file=sys.stderr)
        return 1
    finally:
        await engine.dispose()
    print("User created.")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--email", required=True)
    ap.add_argument("--name", required=True)
    a = ap.parse_args()
    sys.exit(asyncio.run(main(a.email, a.name)))
