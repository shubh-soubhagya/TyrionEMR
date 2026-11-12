"""Internal reads for lab-svc and ai-svc (LLD §12). Read-only; the audited ones do their read and the audit
insert in one short transaction, so an unaudited chart read cannot happen (§19.3)."""
from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.config import Settings
from app.core.errors import NotFound
from app.core.security import User
from app.domain.clock import Clock, today_in
from app.domain.patient_rules import age_on
from app.repositories import internal as repo

TOOL_ROW_CAP = 50
NOTE_FIELDS = ("examination_notes", "assessment", "plan")


def _json(value: Any) -> Any:
    """json_agg/json_build_object come back as text from asyncpg when no codec is registered."""
    return json.loads(value) if isinstance(value, str) else value


class InternalService:
    def __init__(self, session: AsyncSession, settings: Settings, clock: Clock) -> None:
        self.session, self.settings, self.clock = session, settings, clock

    def today(self):
        return today_in(self.clock, self.settings.clinic_tz)

    async def basic(self, pid: uuid.UUID) -> dict[str, Any]:
        """One primary-key lookup, not audited (no clinical content)."""
        row = await repo.basic(self.session, pid)
        if row is None:
            raise NotFound()
        return row

    async def chart(self, pid: uuid.UUID, encounters: int, user: User) -> dict[str, Any]:
        async with self.session.begin():
            patient = await repo.patient_clinical(self.session, pid)
            if patient is None:
                raise NotFound()
            patient["age"] = age_on(patient["date_of_birth"], self.today())
            recent = await repo.recent_encounters(self.session, pid, encounters)
            for e in recent:
                e["vitals"], e["diagnoses"] = _json(e["vitals"]), _json(e["diagnoses"])
            result = {
                "patient": patient,
                "conditions": await repo.conditions(self.session, pid, None, 200),
                "medications": await repo.medications(self.session, pid, 200),
                "allergies": await repo.allergies(self.session, pid, 200),
                "recent_encounters": recent,
                "encounter_index": await repo.encounter_index(self.session, pid),
                "counts": await repo.encounter_counts(self.session, pid),
            }
            await self._audit_read(user, pid, "chart")
            return result

    async def conditions(self, pid: uuid.UUID, status: str | None, user: User) -> dict[str, Any]:
        async with self.session.begin():
            await self._require(pid)
            rows = await repo.conditions(self.session, pid, status, TOOL_ROW_CAP + 1)
            await self._audit_read(user, pid, "conditions")
            return {"items": rows[:TOOL_ROW_CAP], "truncated": len(rows) > TOOL_ROW_CAP}

    async def medications_allergies(self, pid: uuid.UUID, user: User) -> dict[str, Any]:
        async with self.session.begin():
            await self._require(pid)
            meds = await repo.medications(self.session, pid, TOOL_ROW_CAP + 1)
            allergies = await repo.allergies(self.session, pid, TOOL_ROW_CAP + 1)
            await self._audit_read(user, pid, "medications-allergies")
            return {"medications": meds[:TOOL_ROW_CAP], "allergies": allergies[:TOOL_ROW_CAP],
                    "truncated": len(meds) > TOOL_ROW_CAP or len(allergies) > TOOL_ROW_CAP}

    async def encounters(self, pid: uuid.UUID, limit: int, include_notes: bool, user: User) -> dict[str, Any]:
        cap = self.settings.internal_note_max_chars
        async with self.session.begin():
            await self._require(pid)
            rows = await repo.recent_encounters(self.session, pid, limit)
            truncated = False
            for e in rows:
                e["vitals"], e["diagnoses"] = _json(e["vitals"]), _json(e["diagnoses"])
                for field in NOTE_FIELDS:
                    if not include_notes:
                        e.pop(field)
                    elif e[field] and len(e[field]) > cap:
                        e[field], truncated = e[field][:cap], True
            await self._audit_read(user, pid, "encounters")
            return {"items": rows, "truncated": truncated}

    async def bulk_charts(self, cursor: uuid.UUID | None, limit: int, user: User) -> dict[str, Any]:
        limit = min(limit, self.settings.internal_bulk_max_limit)
        async with self.session.begin():
            rows = await repo.bulk_charts(self.session, cursor, limit, self.today())
            more = len(rows) > limit
            page = rows[:limit]
            today = self.today()
            for r in page:
                r["age"] = age_on(r["date_of_birth"], today)
                r["active_meds_past_end"] = _json(r["active_meds_past_end"])
                r["final_encounters"] = _json(r["final_encounters"])
                r["medication_count"] = int(r["medication_count"])
            # one audit row per page, not per patient (system-wide aggregate, §12.5)
            await audit.record(self.session, actor_id=user.id, action="chart.bulk_export", resource="patients",
                               details={"count": len(page)})
            return {"items": page, "next_cursor": str(page[-1]["id"]) if more else None}

    async def _require(self, pid: uuid.UUID) -> None:
        if await repo.basic(self.session, pid) is None:
            raise NotFound()

    async def _audit_read(self, user: User, pid: uuid.UUID, what: str) -> None:
        await audit.record(self.session, actor_id=user.id, action="chart.read_internal", resource="patient",
                           patient_id=pid, resource_id=pid, details={"read": what})
