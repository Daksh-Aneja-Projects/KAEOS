"""
KAEOS Healthcare Domain — Core Models

Four tenant-scoped, RLS-ready tables that back the clinical operations
department. Deliberately minimal PHI: encounters carry a pseudonymous
``patient_ref`` and coded facts, never free-text identifiers, so demo data and
the analytics surface never hold real protected health information.

  hlth_encounters        PatientEncounter  — a clinical visit + its coding state
  hlth_phi_disclosures   PHIDisclosure     — an outbound PHI release (gated)
  hlth_consent_records   ConsentRecord     — patient consent (incl. 42 CFR Part 2)
  hlth_clinical_tasks    ClinicalTask      — coding / prior-auth work items
"""
from sqlalchemy import (
    Boolean, Column, DateTime, ForeignKey, JSON, String, Text, UniqueConstraint,
)
from sqlalchemy.sql import func
import uuid

from app.models.domain import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class PatientEncounter(Base):
    """A clinical encounter. ``patient_ref`` is a pseudonymous handle, not a
    name or MRN - the encounter row itself never stores a direct identifier."""
    __tablename__ = "hlth_encounters"
    __table_args__ = (
        UniqueConstraint("tenant_id", "encounter_number",
                         name="uq_hlth_encounter_tenant_number"),
    )

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)

    encounter_number = Column(String(32), nullable=False)
    patient_ref = Column(String(64), nullable=False)          # pseudonymous
    encounter_type = Column(String(32), nullable=False)        # office_visit, telehealth, inpatient
    status = Column(String(24), nullable=False, default="OPEN")  # OPEN|TRIAGED|CODED|CLOSED

    reason = Column(String(256), nullable=True)                # chief complaint, minimal
    diagnosis_codes = Column(JSON, default=list)               # ICD-10 codes (coded, not PHI text)
    priority = Column(String(16), nullable=True)               # ROUTINE|URGENT|EMERGENT

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class PHIDisclosure(Base):
    """An outbound disclosure of protected health information. A row exists ONLY
    for a disclosure that passed the HIPAA gate in phi_disclosure.record_disclosure
    - ``authorized`` is always True on a persisted row. A blocked disclosure is
    never recorded (the ledger holds the denial instead)."""
    __tablename__ = "hlth_phi_disclosures"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)

    encounter_id = Column(String, ForeignKey("hlth_encounters.id"), nullable=True, index=True)
    purpose = Column(String(48), nullable=False)               # payment, treatment, marketing, ...
    recipient = Column(String(128), nullable=False)
    fields = Column(JSON, default=list)                        # the disclosed field names
    minimum_necessary_justification = Column(Text, nullable=False)
    part2 = Column(Boolean, default=False)                     # touched substance-use records
    authorized = Column(Boolean, default=True, nullable=False)

    recorded_by = Column(String, nullable=True)                # approver_identity hash
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class ConsentRecord(Base):
    """Patient consent for a disclosure scope. ``part2`` flags a 42 CFR Part 2
    substance-use-disorder consent, which is stricter than a general HIPAA
    authorization. A consent is active when ``revoked_at`` is NULL."""
    __tablename__ = "hlth_consent_records"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)

    patient_ref = Column(String(64), nullable=False)
    scope = Column(String(64), nullable=False)                 # e.g. treatment, research, part2_disclosure
    part2 = Column(Boolean, default=False)                     # 42 CFR Part 2 consent
    granted_at = Column(DateTime(timezone=True), server_default=func.now())
    revoked_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    @property
    def active(self) -> bool:
        return self.revoked_at is None


class ClinicalTask(Base):
    """A work item for the clinical operations department (medical coding,
    prior-authorization, etc.)."""
    __tablename__ = "hlth_clinical_tasks"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)

    encounter_id = Column(String, ForeignKey("hlth_encounters.id"), nullable=True, index=True)
    task_type = Column(String(32), nullable=False)             # coding, prior_auth, ...
    status = Column(String(24), nullable=False, default="OPEN")  # OPEN|IN_PROGRESS|PENDING_HITL|DONE|BLOCKED
    assignee = Column(String(64), nullable=True)
    detail = Column(JSON, default=dict)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
