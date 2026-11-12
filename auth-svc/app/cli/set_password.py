"""Set a clinician's password (the password is prompted twice, never passed on the command line).
Applies the signup policy, clears any lock and signs the user out everywhere.

    python -m app.cli.set_password --email dr.rao@nephrocare.demo
"""
from __future__ import annotations

import asyncio
import getpass
import sys
from collections.abc import Callable

from app.cli._runtime import admin_service, email_parser, explain, parse_email
from app.core.errors import AppError


async def main(argv: list[str], ask: Callable[[str], str] = getpass.getpass) -> int:
    args = email_parser("set_password", __doc__.splitlines()[0]).parse_args(argv)
    email = parse_email(args.email)
    password = ask("New password: ")
    if password != ask("Repeat password: "):
        print("Passwords do not match. Nothing changed.", file=sys.stderr)
        return 2
    async with admin_service() as svc:
        try:
            result = await svc.set_password(email, password)
        except AppError as exc:
            print(f"Nothing changed: {explain(exc)}", file=sys.stderr)
            return 2 if exc.status_code == 422 else 1
    print(f"Password updated for {email}. Lock cleared. {result.sessions_revoked} session(s) signed out.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
