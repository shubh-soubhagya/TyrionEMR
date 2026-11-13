"""Synthetic lab data for the ten demo patients (LLD B11.2, HLD 18). All values are invented.

Goes through the production write path (``ReportService.create_with_basic``), so flags, range snapshots, the
read model and audit rows are exactly what a clinician entering the same report would produce. Dates are
relative to "today" (``SEED_ANCHOR_DATE`` overrides it), so the demo never goes stale: "no labs for 180+ days"
stays true. A random generator seeded per patient makes every run produce the same digits.

Idempotent by default: a patient that already has reports is skipped, so it is safe on every container start.
``--reset`` empties the lab data first and needs ``SEED_ALLOW_RESET=true`` and a non-production environment.

Patient ids are the UUIDv5 ids patient-svc uses (namespace in app/domain/seed_ids.py).

Usage: python -m app.cli.seed_labs [--reset]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings, get_settings
from app.core.security import User
from app.db.session import create_engine, create_sessionmaker
from app.domain.clock import Clock, utcnow
from app.domain.egfr import creatinine_for_egfr
from app.domain.flagging import age_on
from app.domain.seed_ids import patient_id, user_id
from app.schemas.reports import ReportIn, ResultIn
from app.services.catalog import CatalogCache
from app.services.patient_client import PatientBasic
from app.services.reports import ReportService

ENTERED_BY = user_id("dr.rao@nephrocare.demo")
LAB_NAME = "Lotus Clinic Laboratory"
DATA = Path(__file__).resolve().parents[1] / "domain" / "data" / "seed_patients.json"


@dataclass(frozen=True)
class Profile:
    """One row of the LLD B11.2 table."""

    mrn: str
    reports: int
    egfr_first: float
    egfr_last: float
    span_days: int                          # first to last report
    last_days_ago: int                      # age of the most recent report
    k: float
    hb: float
    ca: float
    phos: float
    uacr: float
    k_last: float | None = None             # the final potassium when it differs from the base
    umol_report: int | None = None          # 1-based report whose creatinine is entered in umol/L
    discordance_last: float = 0.0           # last reported eGFR exceeds the creatinine-derived one by this much
    why: str = ""


PROFILES: tuple[Profile, ...] = (
    Profile("PT-000101", 8, 54, 38, 700, 20, 5.2, 11.6, 9.0, 4.4, 480, umol_report=4,
            why="rapid decline, A3, one creatinine in umol/L"),
    Profile("PT-000102", 7, 58, 55, 800, 35, 4.6, 12.6, 9.4, 3.8, 120, why="stable baseline"),
    Profile("PT-000103", 6, 82, 78, 600, 50, 4.3, 14.5, 9.6, 3.4, 210, why="mostly normal"),
    Profile("PT-000104", 7, 34, 24, 540, 12, 5.4, 9.8, 8.2, 5.6, 650, k_last=5.5, why="advanced, rapid decline"),
    Profile("PT-000105", 4, 30, 74, 150, 14, 4.4, 13.9, 9.2, 3.6, 40, why="post-AKI recovery (improving)"),
    Profile("PT-000106", 6, 44, 38, 700, 28, 4.8, 12.2, 9.1, 4.0, 55, why="latest G3b while patient-svc has G4"),
    Profile("PT-000107", 5, 76, 72, 500, 230, 4.5, 14.1, 9.5, 3.5, 85, discordance_last=16,
            why="no labs for 230 days; last eGFR disagrees with creatinine"),
    Profile("PT-000108", 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, why="no labs at all"),
    Profile("PT-000109", 6, 19, 11, 400, 6, 5.9, 9.1, 7.9, 6.4, 900, k_last=6.2,
            why="critical potassium and creatinine"),
    Profile("PT-000110", 5, 59, 49, 500, 25, 4.2, 11.5, 9.0, 3.9, 320, why="low eGFR, no established stage"),
)


def load_patients() -> dict[str, PatientBasic]:
    rows = json.loads(DATA.read_text(encoding="utf-8"))["patients"]
    return {r["mrn"]: PatientBasic(r["sex"], date.fromisoformat(r["date_of_birth"])) for r in rows}


def _q(v: float, places: int) -> float:
    return float(Decimal(str(v)).quantize(Decimal(1).scaleb(-places)))


def generate(p: Profile, basic: PatientBasic, now: datetime) -> list[ReportIn]:
    """The reports of one profile, oldest first. Pure given ``now``.

    Report k of n is collected ``last_days + span * (1 - k/(n-1))`` days ago. eGFR moves linearly from the first
    to the last value with +-1.5 noise (exact at both ends). Creatinine is derived from eGFR with CKD-EPI 2021 for
    the patient's age and sex at that date, so the two agree; BUN follows creatinine.
    """
    n = p.reports
    rng = random.Random(f"lab-seed-42:{p.mrn}")
    out: list[ReportIn] = []
    for k in range(n):
        frac = 0.0 if n == 1 else k / (n - 1)
        days_ago = p.last_days_ago + p.span_days * (1 - frac)
        collected = datetime.combine((now - timedelta(days=round(days_ago))).date(), time(9, 0), tzinfo=UTC)
        egfr = p.egfr_first + (p.egfr_last - p.egfr_first) * frac
        if 0 < k < n - 1:
            egfr += rng.uniform(-1.5, 1.5)
        egfr = round(egfr, 1)
        last = k == n - 1
        age = age_on(basic.date_of_birth, collected.date())
        derived_from = egfr - (p.discordance_last if last else 0.0)
        creat = round(creatinine_for_egfr(derived_from, age, basic.sex), 2)
        bun = round(10 + 8 * creat + rng.uniform(-2, 2), 1)
        potassium = p.k_last if (last and p.k_last is not None) else p.k + rng.uniform(-0.2, 0.2)
        if p.umol_report == k + 1:
            creat_result = ResultIn(test_code="CREAT", value=Decimal(str(_q(creat / 0.0113, 1))), unit="µmol/L")
        else:
            creat_result = ResultIn(test_code="CREAT", value=Decimal(str(creat)), unit="mg/dL")
        results = [
            ResultIn(test_code="EGFR", value=Decimal(str(egfr)), unit="mL/min/1.73m²"), creat_result,
            ResultIn(test_code="BUN", value=Decimal(str(bun)), unit="mg/dL"),
            ResultIn(test_code="K", value=Decimal(str(_q(potassium, 1))), unit="mmol/L"),
            ResultIn(test_code="HB", value=Decimal(str(_q(p.hb + rng.uniform(-0.3, 0.3), 1))), unit="g/dL"),
            ResultIn(test_code="CA", value=Decimal(str(_q(p.ca + rng.uniform(-0.2, 0.2), 1))), unit="mg/dL"),
            ResultIn(test_code="PHOS", value=Decimal(str(_q(p.phos + rng.uniform(-0.2, 0.2), 1))), unit="mg/dL"),
        ]
        if (n - 1 - k) % 2 == 0:                           # UACR on every other report, and always the last
            results.append(ResultIn(test_code="UACR", value=Decimal(str(round(p.uacr * rng.uniform(0.95, 1.05)))),
                                    unit="mg/g"))
        out.append(ReportIn(collected_at=collected, lab_name=LAB_NAME, notes=None, results=results))
    return out


def anchor(settings: Settings, clock: Clock) -> datetime:
    if settings.seed_anchor_date:
        return datetime.combine(settings.seed_anchor_date, time(12, 0), tzinfo=UTC)
    return clock()


class _NoPatients:
    """The seed never calls patient-svc: create_with_basic is handed the patient's sex and date of birth."""

    async def basic(self, *_a, **_k):                      # pragma: no cover
        raise AssertionError("seed must not call patient-svc")


async def seed(settings: Settings, sessionmaker: async_sessionmaker[AsyncSession], clock: Clock = utcnow,
               reset: bool = False) -> dict[str, int]:
    """Returns {mrn: reports created}. Patients that already have reports are skipped."""
    if reset:
        if settings.environment == "production" or not settings.seed_allow_reset:
            raise SystemExit("--reset needs SEED_ALLOW_RESET=true and a non-production environment")
        async with sessionmaker() as s, s.begin():
            await s.execute(text("TRUNCATE patient_lab_status, lab_results, lab_reports, audit_events"))
    people, user = load_patients(), User(id=ENTERED_BY, role="clinician", raw={})
    catalog = CatalogCache(sessionmaker, settings.catalog_cache_ttl_s)
    now = anchor(settings, clock)
    seed_clock: Clock = lambda: now                       # noqa: E731  collected_at must never look "in the future"
    created: dict[str, int] = {}
    for p in PROFILES:
        pid = patient_id(p.mrn)
        if p.reports == 0:
            continue
        async with sessionmaker() as s, s.begin():
            exists = (await s.execute(text("SELECT 1 FROM lab_reports WHERE patient_id = :p LIMIT 1"),
                                      {"p": pid})).first()
        if exists:
            continue
        for body in generate(p, people[p.mrn], now):
            async with sessionmaker() as s:
                svc = ReportService(s, settings, seed_clock, _NoPatients(), catalog)
                await svc.create_with_basic(pid, body, user, people[p.mrn])
        created[p.mrn] = p.reports
    return created


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()
    settings = get_settings()
    engine = create_engine(settings)
    try:
        created = await seed(settings, create_sessionmaker(engine), reset=args.reset)
        print(f"lab seed: {sum(created.values())} reports for {len(created)} patient(s)")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
