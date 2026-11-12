"""Read-only queries for lab-svc and ai-svc (LLD §12.2-12.5). Never commits, never writes."""
from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def basic(session: AsyncSession, pid: uuid.UUID) -> dict[str, Any] | None:
    row = (await session.execute(text(
        "SELECT id, sex, date_of_birth FROM patients WHERE id = :p AND deleted_at IS NULL"), {"p": pid})
    ).mappings().first()
    return dict(row) if row else None


async def patient_clinical(session: AsyncSession, pid: uuid.UUID) -> dict[str, Any] | None:
    """Clinical fields only: NO name, MRN, phone, email or address (P-12, data minimisation at the source)."""
    row = (await session.execute(text("""
        SELECT id, sex, date_of_birth, allergy_status, established_ckd_stage,
               past_medical_history, family_history, social_history
        FROM patients WHERE id = :p AND deleted_at IS NULL"""), {"p": pid})).mappings().first()
    return dict(row) if row else None


async def conditions(session: AsyncSession, pid: uuid.UUID, status: str | None, limit: int) -> list[dict[str, Any]]:
    where = "patient_id = :p AND deleted_at IS NULL" + (" AND status = :status" if status else "")
    params: dict[str, Any] = {"p": pid, "limit": limit}
    if status:
        params["status"] = status
    rows = (await session.execute(text(f"""
        SELECT id, icd10_code, description, category, is_primary, status, onset_date, resolved_date
        FROM patient_conditions WHERE {where}
        ORDER BY is_primary DESC, (category = 'nephrology') DESC, onset_date DESC NULLS LAST, id
        LIMIT :limit"""), params)).mappings().all()
    return [dict(r) for r in rows]


async def medications(session: AsyncSession, pid: uuid.UUID, limit: int) -> list[dict[str, Any]]:
    """Includes discontinued ones: the AI context lists active ones and the rules need end dates (§12.3)."""
    rows = (await session.execute(text("""
        SELECT id, name, dose, route, frequency, start_date, end_date, status
        FROM medications WHERE patient_id = :p AND deleted_at IS NULL
        ORDER BY (status = 'active') DESC, start_date DESC NULLS LAST, id LIMIT :limit"""),
        {"p": pid, "limit": limit})).mappings().all()
    return [dict(r) for r in rows]


async def allergies(session: AsyncSession, pid: uuid.UUID, limit: int) -> list[dict[str, Any]]:
    rows = (await session.execute(text("""
        SELECT id, allergen, reaction, severity FROM allergies
        WHERE patient_id = :p AND deleted_at IS NULL ORDER BY lower(allergen), id LIMIT :limit"""),
        {"p": pid, "limit": limit})).mappings().all()
    return [dict(r) for r in rows]


async def recent_encounters(session: AsyncSession, pid: uuid.UUID, limit: int) -> list[dict[str, Any]]:
    """Newest first, with vitals and diagnoses (drafts included, flagged by ``status``)."""
    rows = (await session.execute(text("""
        SELECT e.id, e.encounter_date, e.encounter_type, e.status, e.chief_complaint, e.symptoms,
               e.examination_notes, e.assessment, e.plan, e.follow_up_date,
               CASE WHEN v.encounter_id IS NULL THEN NULL ELSE json_build_object(
                 'systolic_bp', v.systolic_bp, 'diastolic_bp', v.diastolic_bp, 'heart_rate', v.heart_rate,
                 'temperature_c', v.temperature_c::float8, 'weight_kg', v.weight_kg::float8) END AS vitals,
               COALESCE((SELECT json_agg(json_build_object('icd10_code', d.icd10_code, 'description', d.description)
                                         ORDER BY d.seq)
                         FROM encounter_diagnoses d WHERE d.encounter_id = e.id), '[]') AS diagnoses
        FROM encounters e LEFT JOIN encounter_vitals v ON v.encounter_id = e.id
        WHERE e.patient_id = :p AND e.deleted_at IS NULL
        ORDER BY e.encounter_date DESC, e.created_at DESC, e.id LIMIT :limit"""),
        {"p": pid, "limit": limit})).mappings().all()
    return [dict(r) for r in rows]


async def encounter_index(session: AsyncSession, pid: uuid.UUID) -> list[dict[str, Any]]:
    """ALL encounters, so the gap rules see every final encounter, not only the recent ones (§12.3)."""
    rows = (await session.execute(text("""
        SELECT e.id, e.encounter_date, e.status,
               (v.encounter_id IS NOT NULL) AS has_vitals,
               (coalesce(btrim(e.assessment), '') <> '' AND coalesce(btrim(e.plan), '') <> '')
                 AS has_assessment_and_plan
        FROM encounters e LEFT JOIN encounter_vitals v ON v.encounter_id = e.id
        WHERE e.patient_id = :p AND e.deleted_at IS NULL ORDER BY e.encounter_date DESC, e.id"""),
        {"p": pid})).mappings().all()
    return [dict(r) for r in rows]


async def encounter_counts(session: AsyncSession, pid: uuid.UUID) -> dict[str, int]:
    row = (await session.execute(text("""
        SELECT count(*) AS encounters, count(*) FILTER (WHERE status = 'final') AS final_encounters,
               count(*) FILTER (WHERE status = 'draft') AS drafts
        FROM encounters WHERE patient_id = :p AND deleted_at IS NULL"""), {"p": pid})).mappings().one()
    return {k: int(v) for k, v in row.items()}


async def bulk_charts(session: AsyncSession, cursor: uuid.UUID | None, limit: int,
                      today: date) -> list[dict[str, Any]]:
    """Keyset pagination by id. Fetches ``limit + 1`` rows; the extra one tells the caller a next page exists."""
    cursor_sql = "AND p.id > :cursor" if cursor else ""
    params: dict[str, Any] = {"today": today, "limit": limit + 1}
    if cursor:
        params["cursor"] = cursor
    rows = (await session.execute(text(f"""
        SELECT p.id, p.mrn, p.first_name, p.last_name, p.date_of_birth, p.sex, p.allergy_status,
               p.established_ckd_stage,
               EXISTS (SELECT 1 FROM patient_conditions c WHERE c.patient_id = p.id AND c.is_primary
                       AND c.status = 'active' AND c.deleted_at IS NULL) AS has_active_primary,
               (SELECT count(*) FROM medications m WHERE m.patient_id = p.id AND m.deleted_at IS NULL)
                 AS medication_count,
               COALESCE((SELECT json_agg(json_build_object('id', m.id, 'name', m.name, 'end_date', m.end_date))
                         FROM medications m WHERE m.patient_id = p.id AND m.status = 'active'
                           AND m.end_date < :today AND m.deleted_at IS NULL), '[]') AS active_meds_past_end,
               COALESCE((SELECT json_agg(json_build_object(
                                  'id', e.id, 'encounter_date', e.encounter_date,
                                  'has_vitals', v.encounter_id IS NOT NULL,
                                  'has_assessment_and_plan',
                                  coalesce(btrim(e.assessment), '') <> '' AND coalesce(btrim(e.plan), '') <> '')
                                ORDER BY e.encounter_date DESC)
                         FROM encounters e LEFT JOIN encounter_vitals v ON v.encounter_id = e.id
                         WHERE e.patient_id = p.id AND e.status = 'final' AND e.deleted_at IS NULL), '[]')
                 AS final_encounters
        FROM patients p WHERE p.deleted_at IS NULL {cursor_sql}
        ORDER BY p.id LIMIT :limit"""), params)).mappings().all()
    return [dict(r) for r in rows]
