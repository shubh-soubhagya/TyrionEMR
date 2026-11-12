"""Sign a clinician out everywhere (revoke every refresh-token family).
Access tokens already issued remain valid until they expire (at most 15 minutes).

    python -m app.cli.revoke_sessions --email dr.rao@nephrocare.demo
"""
from __future__ import annotations

import asyncio
import sys

from app.cli._runtime import admin_service, email_parser, explain, parse_email
from app.core.errors import AppError


async def main(argv: list[str]) -> int:
    args = email_parser("revoke_sessions", __doc__.splitlines()[0]).parse_args(argv)
    email = parse_email(args.email)
    async with admin_service() as svc:
        try:
            result = await svc.revoke_sessions(email)
        except AppError as exc:
            print(f"Nothing changed: {explain(exc)}", file=sys.stderr)
            return 1
    print(f"{email}: {result.sessions_revoked} session(s) signed out.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
