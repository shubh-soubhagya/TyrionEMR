"""Deterministic ids for synthetic seed data.

The namespace MUST equal patient-svc's (patient-svc/app/domain/seed_ids.py), so a seeded lab result points at
the patient patient-svc seeded for the same MRN without any call between the services. patient-svc's code is
the reference: its design doc and lab-svc's disagree, and the running code wins.
"""
from __future__ import annotations

import uuid

SEED_NAMESPACE = uuid.UUID("9b3f6a52-7c1e-4d0b-9a58-2f4e8c1d7a10")


def patient_id(mrn: str) -> uuid.UUID:
    return uuid.uuid5(SEED_NAMESPACE, f"patient:{mrn}")


def user_id(email: str) -> uuid.UUID:
    return uuid.uuid5(SEED_NAMESPACE, f"user:{email.lower()}")
