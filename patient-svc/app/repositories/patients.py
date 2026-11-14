"""Patient persistence. Repositories take a session and never commit (LLD §13)."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.search import SearchSpec, order_by_sql
from app.models import Patient


async def lock_active(session: AsyncSession, pid: uuid.UUID) -> Patient | None:
    """The patient row is the aggregate lock (P-01). Lock order: patients -> encounters -> the rest (§16.1)."""
    res = await session.execute(
        select(Patient).where(Patient.id == pid, Patient.deleted_at.is_(None)).with_for_update())
    return res.scalar_one_or_none()


async def get_active(session: AsyncSession, pid: uuid.UUID) -> Patient | None:
    res = await session.execute(select(Patient).where(Patient.id == pid, Patient.deleted_at.is_(None)))
    return res.scalar_one_or_none()


async def exists(session: AsyncSession, pid: uuid.UUID) -> bool:
    res = await session.execute(select(Patient.id).where(Patient.id == pid, Patient.deleted_at.is_(None)))
    return res.first() is not None


async def insert(session: AsyncSession, values: dict[str, Any]) -> Patient:
    patient = Patient(**values)
    session.add(patient)
    await session.flush()
    await session.refresh(patient)          # server defaults: mrn, version, timestamps, search_name
    return patient


async def reseed_mrn_sequence(session: AsyncSession) -> None:
    await session.execute(text(
        "SELECT setval('patient_mrn_seq', greatest((SELECT coalesce(max(substring(mrn FROM 4)::int), 100) "
        "FROM patients), 100))"))


async def update_versioned(session: AsyncSession, pid: uuid.UUID, version: int, values: dict[str, Any],
                           user_id: uuid.UUID) -> int | None:
    """``UPDATE ... WHERE version = :v`` against the version the CLIENT sent (not the one the ORM loaded)."""
    res = await session.execute(
        update(Patient)
        .where(Patient.id == pid, Patient.version == version, Patient.deleted_at.is_(None))
        .values(**values, version=Patient.version + 1, updated_by=user_id)
        .returning(Patient.version).execution_options(synchronize_session=False))
    return res.scalar_one_or_none()


async def bump_version(session: AsyncSession, pid: uuid.UUID, user_id: uuid.UUID, **values: Any) -> int:
    res = await session.execute(
        update(Patient).where(Patient.id == pid)
        .values(**values, version=Patient.version + 1, updated_by=user_id)
        .returning(Patient.version).execution_options(synchronize_session=False))
    return res.scalar_one()


async def raise_last_visit(session: AsyncSession, pid: uuid.UUID, visit: datetime) -> None:
    """Final encounters are immutable and only drafts can be deleted, so the last visit can only move forward.
    Writes only ``last_visit`` (no version bump: it is a derived sort key)."""
    await session.execute(
        text("UPDATE patients SET last_visit = :v WHERE id = :p AND (last_visit IS NULL OR last_visit < :v)"),
        {"v": visit, "p": pid})


async def refresh_primary_dx_sort(session: AsyncSession, pid: uuid.UUID) -> None:
    """Recompute ``primary_dx_sort`` from the problem list. Called at the end of every transaction that can change
    the active primary condition (never a trigger). Writes only that column and only when it changes."""
    await session.execute(text("""
        WITH v AS (
          SELECT (SELECT lower(c.description) FROM patient_conditions c
                  WHERE c.patient_id = :p AND c.is_primary AND c.status = 'active' AND c.deleted_at IS NULL
                  LIMIT 1) AS val)
        UPDATE patients SET primary_dx_sort = v.val FROM v
        WHERE id = :p AND primary_dx_sort IS DISTINCT FROM v.val"""), {"p": pid})


async def soft_delete(session: AsyncSession, pid: uuid.UUID, user_id: uuid.UUID) -> None:
    await session.execute(
        update(Patient).where(Patient.id == pid, Patient.deleted_at.is_(None))
        .values(deleted_at=func.now(), updated_by=user_id, version=Patient.version + 1)
        .execution_options(synchronize_session=False))


async def detail_extras(session: AsyncSession, pid: uuid.UUID, today: date) -> dict[str, Any]:
    """Everything the detail view needs besides the patient row, in two round trips."""
    agg = (await session.execute(text("""
        SELECT
          (SELECT count(*) FROM patient_conditions WHERE patient_id = :p AND deleted_at IS NULL) AS conditions,
          (SELECT count(*) FROM patient_conditions
            WHERE patient_id = :p AND deleted_at IS NULL AND status = 'active') AS active_conditions,
          (SELECT count(*) FROM medications
            WHERE patient_id = :p AND deleted_at IS NULL AND status = 'active') AS active_medications,
          (SELECT count(*) FROM encounters WHERE patient_id = :p AND deleted_at IS NULL) AS encounters,
          (SELECT max(encounter_date) FROM encounters
            WHERE patient_id = :p AND status = 'final' AND deleted_at IS NULL) AS last_visit,
          (SELECT min(follow_up_date) FROM encounters
            WHERE patient_id = :p AND status = 'final' AND deleted_at IS NULL
              AND follow_up_date >= :today) AS next_follow_up
    """), {"p": pid, "today": today})).mappings().one()
    allergies = (await session.execute(text("""
        SELECT id, allergen, severity FROM allergies
        WHERE patient_id = :p AND deleted_at IS NULL ORDER BY lower(allergen)
    """), {"p": pid})).mappings().all()
    primary = (await session.execute(text("""
        SELECT id, icd10_code, description FROM patient_conditions
        WHERE patient_id = :p AND is_primary AND status = 'active' AND deleted_at IS NULL LIMIT 1
    """), {"p": pid})).mappings().first()
    return {"agg": dict(agg), "allergies": [dict(a) for a in allergies], "primary": dict(primary) if primary else None}


def _filters(*, sex: str | None, stage: str | None, ids: list[uuid.UUID] | None,
             search: SearchSpec) -> tuple[str, dict[str, Any]]:
    """WHERE fragments are added only when the filter is present (asyncpg cannot type-infer ``:x IS NULL``)."""
    where = ["p.deleted_at IS NULL"]
    params: dict[str, Any] = {}
    if sex:
        where.append("p.sex = :sex")
        params["sex"] = sex
    if stage == "none":
        where.append("p.established_ckd_stage IS NULL")
    elif stage:
        where.append("p.established_ckd_stage = :stage")
        params["stage"] = stage
    if ids is not None:
        where.append("p.id = ANY(:ids)")
        params["ids"] = ids
    if search.kind == "mrn_prefix":
        where.append("p.mrn LIKE :mrn_like")
        params["mrn_like"] = search.value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    elif search.kind == "mrn_digits":
        where.append("(p.mrn = 'PT-' || lpad(:digits, 6, '0') OR p.mrn LIKE 'PT-' || :digits || '%')")
        params["digits"] = search.value
    elif search.kind == "name":
        for i, tok in enumerate(search.tokens):
            where.append(f"p.search_name LIKE :tok{i} ESCAPE '\\'")
            params[f"tok{i}"] = f"%{tok}%"
    return " AND ".join(where), params


async def list_patients(session: AsyncSession, *, sex: str | None, stage: str | None, ids: list[uuid.UUID] | None,
                        search: SearchSpec, sort: str, direction: str, page: int, size: int,
                        today: date, relevance_q: str | None = None) -> tuple[list[dict[str, Any]], int]:
    where, params = _filters(sex=sex, stage=stage, ids=ids, search=search)
    order = order_by_sql(sort, direction)
    if relevance_q:                                              # name search with no explicit sort (§15.1)
        order = "similarity(f.search_name, :relevance_q) DESC, " + order
        params["relevance_q"] = relevance_q
    filtered = f"""
          SELECT p.id, p.mrn, p.first_name, p.last_name, p.date_of_birth, p.sex, p.phone,
                 p.established_ckd_stage, p.allergy_status, p.search_name, p.last_visit AS last_visit_key,
                 p.primary_dx_sort
          FROM patients p WHERE {where}"""
    # Every sort key is a column of the patient row (the last two since migration 0004), so the page is sliced first
    # and the two lateral probes run for at most `size` rows, not for every filtered patient.
    head = f"""WITH filtered AS ({filtered}),
        paged AS (SELECT f.*, count(*) OVER () AS total FROM filtered f ORDER BY {order} LIMIT :size OFFSET :offset)
        SELECT f.id, f.mrn, f.first_name, f.last_name, f.sex, f.phone, f.established_ckd_stage, f.allergy_status,
               date_part('year', age(CAST(:today AS date), f.date_of_birth))::int AS age,
               pc.icd10_code AS primary_icd10, pc.description AS primary_description,
               lv.last_visit, f.total
        FROM paged f"""
    tail = f"ORDER BY {order}"
    sql = f"""
        {head}
        LEFT JOIN LATERAL (
          SELECT c.icd10_code, c.description FROM patient_conditions c
          WHERE c.patient_id = f.id AND c.is_primary AND c.status = 'active' AND c.deleted_at IS NULL LIMIT 1
        ) pc ON true
        LEFT JOIN LATERAL (
          SELECT max(e.encounter_date) AS last_visit FROM encounters e
          WHERE e.patient_id = f.id AND e.status = 'final' AND e.deleted_at IS NULL
        ) lv ON true
        {tail}
    """
    rows = (await session.execute(text(sql), {**params, "today": today, "size": size,
                                              "offset": (page - 1) * size})).mappings().all()
    if rows:
        return [dict(r) for r in rows], int(rows[0]["total"])
    # A page past the end returns no rows and therefore no window total: count separately (§15.2)
    total = (await session.execute(text(f"SELECT count(*) FROM patients p WHERE {where}"), params)).scalar_one()
    return [], int(total)
