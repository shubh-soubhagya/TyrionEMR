"""Clear a clinician's lockout and failed-login counter.

    python -m app.cli.unlock_user --email dr.rao@nephrocare.demo
"""
from __future__ import annotations

import asyncio
import sys

from app.cli._runtime import admin_service, email_parser, explain, parse_email
from app.core.errors import AppError


async def main(argv: list[str]) -> int:
    args = email_parser("unlock_user", __doc__.splitlines()[0]).parse_args(argv)
    email = parse_email(args.email)
    async with admin_service() as svc:
        try:
            result = await svc.unlock(email)
        except AppError as exc:
            print(f"Nothing changed: {explain(exc)}", file=sys.stderr)
            return 1
    print(f"{email}: " + ("lock and failed-login counter cleared." if result.was_locked
                          else "was not locked and had no failed attempts; nothing to clear."))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
