"""Captures the real upstream responses ai-svc depends on (``make capture-fixtures``, LLD B17.5).

Run it INSIDE the compose network (internal routes are never reachable through the gateway):

    docker compose run --rm --no-deps --build -v <abs path>/tests/fixtures/captured:/out \
        --entrypoint python ai-svc -m app.cli.capture_fixtures --out /out

1. logs in as a demo user THROUGH THE GATEWAY (``GATEWAY_URL``, default ``http://gateway:8000``) and keeps the
   access token in memory only;
2. calls patient-svc and lab-svc ``/internal`` routes directly with that token;
3. writes the raw JSON bodies, unmodified (the data is synthetic), under ``--out``:

    manifest.json                       when, and which patients were captured (rules are evaluated 'as of' then)
    patients/charts.json                every page of /internal/patients/charts (list of pages)
    labs/status.json                    every page of /internal/labs/status (list of pages)
    <MRN>/{basic,chart,conditions,medications-allergies,encounters}.json     patient-svc, two patients
    <MRN>/{latest,trends,results-EGFR}.json                                   lab-svc, the same two patients

Nothing is logged except file names and status codes: no bodies, no tokens.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

# patient-svc's seed namespace (patient-svc/app/domain/seed_ids.py): patient id = uuid5(NS, "patient:" + MRN)
SEED_NAMESPACE = uuid.UUID("9b3f6a52-7c1e-4d0b-9a58-2f4e8c1d7a10")
ALL_MRNS = tuple(f"PT-{n:06d}" for n in range(101, 111))
DEFAULT_MRNS = ("PT-000101", "PT-000110")        # Ramesh Kulkarni (rapid decline) and Kavita Joshi (the B20.1 seed fix)
PAGE = 200


def patient_id(mrn: str) -> uuid.UUID:
    return uuid.uuid5(SEED_NAMESPACE, f"patient:{mrn}")


def write(out: Path, rel: str, body: Any) -> None:
    path = out / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"captured {rel}")


def get(client: httpx.Client, base: str, path: str, token: str, params: dict | None = None) -> Any:
    resp = client.get(f"{base}{path}", params=params, headers={"Authorization": f"Bearer {token}"})
    print(f"GET {path.split('?')[0].replace('/internal', '')[:60]} -> {resp.status_code}")
    resp.raise_for_status()
    return resp.json()


def pages(client: httpx.Client, base: str, path: str, token: str) -> list[Any]:
    out: list[Any] = []
    cursor: str | None = None
    while True:
        params: dict[str, Any] = {"limit": PAGE}
        if cursor:
            params["cursor"] = cursor
        body = get(client, base, path, token, params)
        out.append(body)
        cursor = body.get("next_cursor")
        if not cursor:
            return out


def login(client: httpx.Client, gateway: str, email: str, password: str) -> str:
    resp = client.post(f"{gateway}/api/auth/login", json={"email": email, "password": password})
    print(f"POST /api/auth/login (gateway) -> {resp.status_code}")
    resp.raise_for_status()
    return str(resp.json()["access_token"])


def capture(out: Path, mrns: tuple[str, ...], *, gateway: str, patient_url: str, lab_url: str, email: str,
            password: str) -> None:
    with httpx.Client(timeout=30.0) as client:
        token = login(client, gateway, email, password)
        write(out, "patients/charts.json", pages(client, patient_url, "/internal/patients/charts", token))
        write(out, "labs/status.json", pages(client, lab_url, "/internal/labs/status", token))
        for mrn in mrns:
            pid = patient_id(mrn)
            for name, path, params in (
                ("basic", f"/internal/patients/{pid}/basic", None),
                ("chart", f"/internal/patients/{pid}/chart", {"encounters": 2}),
                ("conditions", f"/internal/patients/{pid}/conditions", None),
                ("medications-allergies", f"/internal/patients/{pid}/medications-allergies", None),
                ("encounters", f"/internal/patients/{pid}/encounters", None),
            ):
                write(out, f"{mrn}/{name}.json", get(client, patient_url, path, token, params))
            for name, path, params in (
                ("latest", f"/internal/labs/patients/{pid}/latest", None),
                ("trends", f"/internal/labs/patients/{pid}/trends", {"tests": "CREAT,EGFR"}),
                ("results-EGFR", f"/internal/labs/patients/{pid}/results", {"test": "EGFR", "size": 50}),
            ):
                write(out, f"{mrn}/{name}.json", get(client, lab_url, path, token, params))
    write(out, "manifest.json", {"captured_at": datetime.now(UTC).isoformat(),
                                 "patients": {m: str(patient_id(m)) for m in mrns}, "all_mrns": list(ALL_MRNS)})


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=Path("tests/fixtures/captured"))
    ap.add_argument("--mrn", action="append", help="repeatable; default: PT-000101 and PT-000110")
    args = ap.parse_args(argv)
    env = os.environ
    capture(args.out, tuple(args.mrn or DEFAULT_MRNS),
            gateway=env.get("GATEWAY_URL", "http://gateway:8000").rstrip("/"),
            patient_url=env.get("PATIENT_SVC_URL", "http://patient-svc:8000").rstrip("/"),
            lab_url=env.get("LAB_SVC_URL", "http://lab-svc:8000").rstrip("/"),
            email=env.get("CAPTURE_EMAIL", "dr.rao@nephrocare.demo"),
            password=env.get("CAPTURE_PASSWORD", "Nephro#2026"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
