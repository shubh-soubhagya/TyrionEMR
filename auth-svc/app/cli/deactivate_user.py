"""Deactivate a clinician: sign-in is refused and every session is signed out.

    python -m app.cli.deactivate_user --email dr.rao@nephrocare.demo
"""
from __future__ import annotations

import asyncio
import sys

from app.cli._runtime import admin_service, email_parser, explain, parse_email
from app.core.errors import AppError


async def main(argv: list[str]) -> int:
    args = email_parser("deactivate_user", __doc__.splitlines()[0]).parse_args(argv)
    email = parse_email(args.email)
    async with admin_service() as svc:
        try:
            result = await svc.deactivate(email)
        except AppError as exc:
            print(f"Nothing changed: {explain(exc)}", file=sys.stderr)
            return 1
    state = "was already inactive" if result.already_inactive else "deactivated"
    print(f"{email}: {state}. {result.sessions_revoked} session(s) signed out.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
