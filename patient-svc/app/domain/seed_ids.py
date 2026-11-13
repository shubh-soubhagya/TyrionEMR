"""Deterministic ids for synthetic seed data (P-03, LLD §23.2).

Seeded patients and clinicians get UUIDv5 ids derived from the MRN / e-mail, so lab-svc's seed can reference the
same patient ids without calling patient-svc.

Resolved: lab-svc and auth-svc's demo-user seed use this same namespace (9b3f6a52-...). Keep it identical in all
three services or lab results and encounter clinicians will point at ids that do not exist.
"""
from __future__ import annotations

import uuid

SEED_NAMESPACE = uuid.UUID("9b3f6a52-7c1e-4d0b-9a58-2f4e8c1d7a10")


def patient_id(mrn: str) -> uuid.UUID:
    return uuid.uuid5(SEED_NAMESPACE, f"patient:{mrn}")


def user_id(email: str) -> uuid.UUID:
    return uuid.uuid5(SEED_NAMESPACE, f"user:{email.lower()}")
