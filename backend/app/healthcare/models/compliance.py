"""
KAEOS Healthcare — Compliance & Reporting

Persisted HIPAA / 42 CFR Part 2 compliance reports and violations, mirroring
HR's ComplianceReport/ComplianceViolation shape (app/hr/models/compliance.py).
Plain string status/framework columns (not a native DB enum), matching every
other status column in this codebase - see the migration for why.
"""
from sqlalchemy import Boolean, Column, DateTime, Integer, JSON, String
from sqlalchemy.sql import func

from app.models.domain import Base
from app.models.mixins import new_uuid as _uuid




class ComplianceReport(Base):
    """A generated compliance report for a tenant (e.g. an annual HIPAA
    disclosure audit). ``data`` holds the derived, real aggregate stats the
    report was built from - never a fabricated figure."""
    __tablename__ = "hlth_compliance_reports"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)

    framework = Column(String(32), nullable=False)             # HIPAA | PART2 | HITECH
    report_name = Column(String(256), nullable=False)          # e.g. "Q2 2026 HIPAA Disclosure Audit"
    period_year = Column(Integer, nullable=False)

    status = Column(String(32), nullable=False, default="GENERATED")  # GENERATED|REVIEWED|SUBMITTED
    data = Column(JSON, nullable=False)                         # the report's derived figures

    generated_at = Column(DateTime(timezone=True), server_default=func.now())
    submitted_at = Column(DateTime(timezone=True), nullable=True)


class ComplianceViolation(Base):
    """A recorded compliance violation (e.g. a blocked disclosure) surfaced for
    tenant review. Distinct from the ProvenanceLedger's PHI_DISCLOSURE_BLOCKED
    entries: this is the reviewable, resolvable compliance-team queue."""
    __tablename__ = "hlth_compliance_violations"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)

    framework = Column(String(64), nullable=False)
    severity = Column(String(32), nullable=False)               # WARNING | BLOCKER
    description = Column(String(512), nullable=False)

    context = Column(JSON, nullable=True)                       # what caused it
    actor_id = Column(String, nullable=True)                    # agent or user who caused it

    resolved = Column(Boolean, default=False)
    resolution_notes = Column(String(512), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
