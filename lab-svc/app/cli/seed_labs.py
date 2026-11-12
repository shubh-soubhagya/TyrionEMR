"""Synthetic lab data for the ten demo patients (HLD 18). All values are invented.

Goes through the REAL write path (ReportService), so flags, snapshots, the read model and audit rows are
exactly what a clinician entering the same report would produce. Day offsets are resolved against "today" at
load time, so the demo never goes stale (for example "no labs for 180+ days" stays true).

Idempotent: a patient that already has reports is skipped. ``--reset`` (development only) empties lab data
first. Patient ids are the UUIDv5 ids patient-svc uses, so the services agree without calling each other.

Usage: python -m app.cli.seed_labs [--reset]
"""
from __future__ import annotations

import argparse
import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import text

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
UNITS = {"CREAT": "mg/dL", "EGFR": "mL/min/1.73m²", "BUN": "mg/dL", "K": "mmol/L", "HB": "g/dL",
         "CA": "mg/dL", "PHOS": "mg/dL", "UACR": "mg/g"}


@dataclass(frozen=True)
class Draw:
    """One blood draw ``days_ago`` days before today. ``creat`` overrides the value derived from eGFR."""

    days_ago: int
    egfr: float
    creat: float | None = None
    extra: dict[str, float] = field(default_factory=dict)
    creat_umol: bool = False                    # enter creatinine in umol/L to exercise unit conversion


@dataclass(frozen=True)
class Scenario:
    mrn: str
    sex: str
    dob: date
    draws: tuple[Draw, ...]
    why: str


def _panel(k: float = 4.4, hb: float = 12.8, bun: float = 22, ca: float = 9.2, phos: float = 3.8, uacr: float = 60):
    return {"K": k, "HB": hb, "BUN": bun, "CA": ca, "PHOS": phos, "UACR": uacr}


SCENARIOS: tuple[Scenario, ...] = (
    Scenario("PT-000101", "M", date(1959, 4, 17), (
        Draw(300, 58, extra=_panel(uacr=380)), Draw(240, 55), Draw(180, 51, extra=_panel(k=4.9, uacr=400)),
        Draw(120, 48, creat_umol=True), Draw(60, 45, extra=_panel(k=5.2, hb=11.4, bun=34, uacr=420)),
        Draw(14, 41, extra=_panel(k=5.4, hb=11.1, bun=38, phos=4.7, uacr=450))),
        "rapid eGFR decline, albuminuria A3, one report entered in umol/L"),
    Scenario("PT-000102", "F", date(1971, 1, 5), tuple(
        Draw(d, e, extra=_panel(hb=12.4, uacr=35) if i % 2 == 0 else {})
        for i, (d, e) in enumerate([(330, 53), (270, 52), (210, 54), (150, 52), (90, 51), (45, 53), (10, 52)])),
        "stable hypertensive CKD"),
    Scenario("PT-000103", "M", date(1985, 7, 30), (
        Draw(200, 74, extra=_panel(hb=14.5, uacr=22)), Draw(100, 72), Draw(20, 73, extra=_panel(hb=14.2, uacr=25))),
        "G2, mostly normal"),
    Scenario("PT-000104", "F", date(1948, 12, 1), tuple(
        Draw(d, e, extra=_panel(k=5.1, hb=10.8, bun=45, phos=5.0, uacr=220) if i % 2 == 0 else {})
        for i, (d, e) in enumerate([(520, 28), (440, 27), (360, 27), (280, 26), (200, 25), (120, 25), (50, 24)])),
        "advanced CKD with steady decline"),
    Scenario("PT-000105", "M", date(1990, 3, 12), (
        Draw(170, 25, extra=_panel(k=5.3, bun=48)), Draw(130, 38), Draw(90, 52), Draw(50, 66), Draw(12, 78,
        extra=_panel(k=4.2, hb=14.0, bun=16, uacr=20))),
        "post-AKI recovery (improving)"),
    Scenario("PT-000106", "F", date(1955, 9, 23), (
        Draw(240, 24), Draw(180, 28, extra=_panel()), Draw(120, 31), Draw(60, 35), Draw(15, 38, extra=_panel(uacr=90))),
        "established G4 but latest eGFR is G3b (stage mismatch)"),
    Scenario("PT-000107", "M", date(1962, 6, 14), (
        Draw(400, 86, creat=2.4, extra=_panel(uacr=40)), Draw(300, 85, creat=2.4), Draw(220, 85, creat=2.5,
        extra=_panel(uacr=45))),
        "no labs for 180+ days; eGFR and creatinine disagree"),
    Scenario("PT-000108", "F", date(1996, 11, 8), (), "near-empty chart: no labs"),
    Scenario("PT-000109", "M", date(1973, 2, 19), (
        Draw(120, 14, extra=_panel(k=5.6, hb=9.4, bun=88, ca=8.1, phos=6.8, uacr=900)),
        Draw(60, 11, extra=_panel(k=6.1, hb=8.9, bun=102, ca=7.8, phos=7.4, uacr=950)),
        Draw(5, 8, creat=6.1, extra=_panel(k=6.8, hb=8.6, bun=118, ca=7.5, phos=8.4, uacr=980))),
        "critical potassium and creatinine"),
    Scenario("PT-000110", "F", date(1992, 4, 20), (
        Draw(260, 49, extra=_panel(hb=11.8, uacr=310)), Draw(170, 47), Draw(90, 48, extra=_panel(hb=11.6, uacr=290)),
        Draw(25, 46)),
        "persistently low eGFR, no established stage"),
)


class _Static:
    """PatientDirectory backed by the scenario table: the seed needs no HTTP."""

    def __init__(self) -> None:
        self.people = {patient_id(s.mrn): PatientBasic(s.sex, s.dob) for s in SCENARIOS}

    async def basic(self, pid: uuid.UUID, authorization: str, request_id: str | None) -> PatientBasic:
        return self.people[pid]


def _report(s: Scenario, d: Draw, now: datetime) -> ReportIn:
    when = (now - timedelta(days=d.days_ago)).replace(hour=9, minute=0, second=0, microsecond=0)
    age = age_on(s.dob, when.date())
    creat = d.creat if d.creat is not None else round(creatinine_for_egfr(d.egfr, age, s.sex), 2)
    results = [ResultIn(test_code="EGFR", value=d.egfr, unit=UNITS["EGFR"])]       # type: ignore[arg-type]
    if d.creat_umol:
        results.append(ResultIn(test_code="CREAT", value=round(creat / 0.0113, 1), unit="µmol/L"))   # type: ignore[arg-type]
    else:
        results.append(ResultIn(test_code="CREAT", value=creat, unit=UNITS["CREAT"]))                 # type: ignore[arg-type]
    results += [ResultIn(test_code=c, value=v, unit=UNITS[c]) for c, v in d.extra.items()]           # type: ignore[arg-type]
    return ReportIn(collected_at=when.astimezone(UTC), lab_name="Lotus Clinic Lab", notes=None, results=results)


async def seed(settings: Settings, sessionmaker, clock: Clock = utcnow, reset: bool = False) -> dict[str, int]:
    if reset:
        if settings.environment == "production":
            raise SystemExit("--reset is for development only")
        async with sessionmaker() as s, s.begin():
            await s.execute(text("TRUNCATE patient_lab_status, lab_results, lab_reports, audit_events"))
    catalog = CatalogCache(sessionmaker, settings.catalog_cache_ttl_s)
    directory, user, now = _Static(), User(id=ENTERED_BY, role="clinician", raw={}), clock()
    created: dict[str, int] = {}
    for sc in SCENARIOS:
        pid = patient_id(sc.mrn)
        if not sc.draws:
            continue
        async with sessionmaker() as s, s.begin():
            exists = (await s.execute(text("SELECT 1 FROM lab_reports WHERE patient_id = :p LIMIT 1"),
                                      {"p": pid})).first()
        if exists:
            continue
        for d in sorted(sc.draws, key=lambda x: -x.days_ago):             # oldest first
            async with sessionmaker() as s:
                svc = ReportService(s, settings, clock, directory, catalog)
                await svc.create(pid, _report(sc, d, now), user, "seed")
        created[sc.mrn] = len(sc.draws)
    return created


async def main() -> None:
    parser = argparse.ArgumentParser()
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
