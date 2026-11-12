"""Idempotent synthetic seed (LLD §23.3).  ``python -m app.cli.seed_patients [--reset] [--scale N]``

Patients are inserted with deterministic ids and explicit MRNs; everything else (conditions, medications,
allergies, encounters) goes through the SAME services the API uses, so seed data obeys every validation,
constraint and trigger. Dates are day offsets resolved against today, so the dashboard always has recent
visits and upcoming follow-ups.

``--scale N`` instead bulk-generates N synthetic patients (about 20 encounters each) with SQL, to measure
the query plans of LLD §26. Refused unless ENVIRONMENT is development or test.
"""
from __future__ import annotations

import asyncio
import json
import sys
import uuid
from datetime import date, datetime, time, timedelta
from importlib import resources
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.core.config import Settings, get_settings
from app.core.security import User
from app.db.session import create_engine, create_sessionmaker
from app.domain.clock import Clock, today_in, utcnow
from app.domain.seed_ids import patient_id, user_id
from app.repositories import patients as patients_repo
from app.schemas.chart import AllergyCreate, ConditionCreate, MedicationCreate
from app.schemas.encounter import DiagnosisIn, EncounterCreate, VitalsIn
from app.services.allergies import AllergyService
from app.services.conditions import ConditionService
from app.services.encounters import EncounterService
from app.services.medications import MedicationService

TABLES = ("audit_events, encounter_diagnoses, encounter_vitals, patient_conditions, medications, allergies, "
          "encounters, patients")


class StaticNames:
    """Seed-time clinician names (the demo accounts), so seeding needs no running auth-svc."""

    def __init__(self, names: dict[uuid.UUID, str]) -> None:
        self._names = names

    async def name_for(self, user_id: uuid.UUID, authorization: str, request_id: str | None) -> str | None:
        return self._names.get(user_id)


def load_data() -> dict[str, Any]:
    return json.loads(resources.files("app.domain").joinpath("data/seed_patients.json").read_text(encoding="utf-8"))


async def seed_scenarios(sm: async_sessionmaker, settings: Settings, clock: Clock) -> tuple[int, int]:
    data = load_data()
    clinicians = {k: User(id=user_id(v["email"]), role="clinician", raw={}) for k, v in data["clinicians"].items()}
    names = StaticNames({user_id(v["email"]): v["name"] for v in data["clinicians"].values()})
    today = today_in(clock, settings.clinic_tz)
    tz = ZoneInfo(settings.clinic_tz)

    def at(days_ago: int) -> datetime:
        return datetime.combine(today - timedelta(days=days_ago), time(10, 0), tzinfo=tz)

    created = skipped = 0
    for p in data["patients"]:
        async with sm() as s:
            exists = (await s.execute(text("SELECT 1 FROM patients WHERE mrn = :m"), {"m": p["mrn"]})).first()
        if exists:
            skipped += 1
            continue
        pid = patient_id(p["mrn"])
        author = clinicians["rao"]
        async with sm() as s, s.begin():
            await patients_repo.insert(s, {
                "id": pid, "mrn": p["mrn"], "first_name": p["first_name"], "last_name": p["last_name"],
                "date_of_birth": date.fromisoformat(p["dob"]), "sex": p["sex"], "phone": p["phone"],
                "email": p["email"], "past_medical_history": p["pmh"], "family_history": p["fh"],
                "social_history": p["sh"], "allergy_status": p["allergy_status"],
                "established_ckd_stage": p["stage"], "created_by": author.id, "updated_by": author.id})
        for c in p["conditions"]:
            async with sm() as s:
                await ConditionService(s, settings, clock).create(pid, ConditionCreate(
                    icd10_code=c["icd10"], description=c["description"], category=c["category"],
                    onset_date=today - timedelta(days=c["onset_days_ago"]), is_primary=c.get("primary", False)), author)
        for m in p["medications"]:
            end = today - timedelta(days=m["end_days_ago"]) if "end_days_ago" in m else None
            async with sm() as s:
                await MedicationService(s, settings, clock).create(pid, MedicationCreate(
                    name=m["name"], dose=m["dose"], route=m.get("route", "oral"), frequency=m["frequency"],
                    start_date=today - timedelta(days=m["start_days_ago"]), end_date=end), author)
        for a in p["allergies"]:
            async with sm() as s:
                await AllergyService(s).create(pid, AllergyCreate(**a), author)
        for e in p["encounters"]:
            status = e.get("status", "final")
            follow_up = today + timedelta(days=e["follow_up_in_days"]) if "follow_up_in_days" in e else None
            body = EncounterCreate(
                encounter_date=at(e["days_ago"]), encounter_type=e["type"], chief_complaint=e["cc"],
                assessment=e.get("assessment"), plan=e.get("plan"), follow_up_date=follow_up,
                vitals=VitalsIn(**e["vitals"]) if e.get("vitals") else None,
                diagnoses=[DiagnosisIn(icd10_code=i, description=d, add_to_problem_list=add)
                           for i, d, add in e.get("dx", [])],
                status=status)
            async with sm() as s:
                await EncounterService(s, settings, clock, directory=names).create(pid, body, clinicians[e["doc"]])
        created += 1
    async with sm() as s, s.begin():
        await patients_repo.reseed_mrn_sequence(s)          # the next registration gets PT-000111
    return created, skipped


async def reset(engine: AsyncEngine) -> None:
    """TRUNCATE bypasses the no-delete triggers; only ever allowed outside production (§23.3)."""
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))
        await conn.execute(text("ALTER SEQUENCE patient_mrn_seq RESTART WITH 101"))


async def seed_scale(engine: AsyncEngine, patients: int, encounters_each: int = 20) -> None:
    """Bulk synthetic data by SQL (LLD §26). Encounters are inserted as drafts, given vitals, then finalized,
    because the triggers freeze the children of a final encounter."""
    async with engine.begin() as conn:
        # bulk load: the service's 3 s statement cap does not apply
        await conn.execute(text("SET LOCAL statement_timeout = 0"))
        await conn.execute(text("""
            INSERT INTO patients (first_name, last_name, date_of_birth, sex, established_ckd_stage, allergy_status)
            SELECT 'First' || g, 'Last' || (g % 997), DATE '1940-01-01' + (random() * 20000)::int,
                   (ARRAY['M','F','O'])[1 + g % 3],
                   (ARRAY['G1','G2','G3a','G3b','G4','G5',NULL])[1 + g % 7],
                   (ARRAY['unknown','nka'])[1 + g % 2]
            FROM generate_series(1, :n) g"""), {"n": patients})
        await conn.execute(text("""
            INSERT INTO patient_conditions (patient_id, icd10_code, description, category, is_primary)
            SELECT id, 'N18.31', 'Primary diagnosis', 'nephrology', true
            FROM patients"""))
        await conn.execute(text("""
            INSERT INTO medications (patient_id, name, dose, frequency)
            SELECT p.id, 'Drug ' || m, '10 mg', 'Once daily' FROM patients p, generate_series(1, 3) m"""))
        await conn.execute(text("""
            INSERT INTO encounters (patient_id, encounter_date, clinician_id, clinician_name, created_by,
                                    chief_complaint, assessment, plan, follow_up_date)
            SELECT p.id, now() - (e * 30 + (random() * 20)::int || ' days')::interval, gen_random_uuid(),
                   'Dr Synthetic', gen_random_uuid(), 'Review', 'Stable', 'Continue',
                   CASE WHEN e = 1 THEN current_date + (random() * 60)::int END
            FROM patients p, generate_series(1, :e) e"""), {"e": encounters_each})
        await conn.execute(text("""
            INSERT INTO encounter_vitals (encounter_id, systolic_bp, diastolic_bp, heart_rate)
            SELECT id, 130, 80, 72 FROM encounters WHERE random() < 0.9"""))
        await conn.execute(text("UPDATE encounters SET status = 'final', finalized_at = now()"))
        await conn.execute(text("ANALYZE"))


async def main(argv: list[str]) -> int:
    settings = get_settings()
    if settings.environment == "production":
        print("Refusing to seed: ENVIRONMENT=production.", file=sys.stderr)
        return 1
    engine = create_engine(settings)
    try:
        if "--reset" in argv:
            await reset(engine)
        if "--scale" in argv:
            await seed_scale(engine, int(argv[argv.index("--scale") + 1]))
            print("scale seed complete")
            return 0
        created, skipped = await seed_scenarios(create_sessionmaker(engine), settings, utcnow)
        print(f"seed complete: {created} created, {skipped} already present")
    finally:
        await engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
