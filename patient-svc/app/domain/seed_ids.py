"""Deterministic ids for synthetic seed data (P-03, LLD §23.2).

Seeded patients and clinicians get UUIDv5 ids derived from the MRN / e-mail, so lab-svc's seed can reference the
same patient ids without calling patient-svc.

NOTE (open item): the patient-svc design uses namespace 9b3f6a52-..., while lab-svc's design lists
6f1c2d3e-.... The two services must share ONE namespace or lab results will point at patients that do not
exist. This constant is the single place to change; agree on it before seeding lab-svc.
"""
from __future__ import annotations

import uuid

SEED_NAMESPACE = uuid.UUID("9b3f6a52-7c1e-4d0b-9a58-2f4e8c1d7a10")


def patient_id(mrn: str) -> uuid.UUID:
    return uuid.uuid5(SEED_NAMESPACE, f"patient:{mrn}")


def user_id(email: str) -> uuid.UUID:
    return uuid.uuid5(SEED_NAMESPACE, f"user:{email.lower()}")
