"""
KAEOS Operations Domain — Facilities Models

Work orders raised against physical/IT facilities: routine maintenance
changes, safety incidents, and asset decommissions. Backs FacilityAgent,
which deterministically triages priority and feeds the three purpose-built
Operations ITGC checkers (CHANGE_MANAGEMENT, INCIDENT_POSTMORTEM,
BACKUP_RETENTION — app/compliance/checkers/operations.py) real, DB-backed
context selected by the order's category:
  MAINTENANCE  -> change   (is_production/implementer/approver/change_ticket)
  SAFETY       -> incident (severity/status/root_cause/action_items)
  DECOMMISSION -> retention (backup_verified/record_age_days/retention_days)
"""
from sqlalchemy import Boolean, Column, DateTime, Float, String, Text
from sqlalchemy.sql import func

from app.models.domain import Base
from app.models.mixins import new_uuid as _uuid




class WorkOrder(Base):
    """Facility maintenance / safety / decommission work orders."""
    __tablename__ = "ops_work_orders"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)

    facility_name = Column(String(256), nullable=False)
    issue_title = Column(String(256), nullable=False)
    description = Column(Text, nullable=True)
    category = Column(String(32), default="MAINTENANCE")  # MAINTENANCE, SAFETY, DECOMMISSION
    severity = Column(String(32), nullable=True)           # raw input, e.g. SEV1, CRITICAL, LOW
    status = Column(String(24), default="OPEN")             # OPEN, IN_PROGRESS, RESOLVED, CLOSED
    reported_by = Column(String(128), nullable=True)

    # FacilityAgent's deterministic triage output (never LLM-guessed).
    priority = Column(String(24), nullable=True)            # URGENT, MEDIUM, LOW, NEEDS_TRIAGE
    assigned_team = Column(String(128), nullable=True)
    scheduled_hours = Column(Float, nullable=True)
    safety_flagged = Column(Boolean, default=False)
    ai_notes = Column(Text, nullable=True)                  # plain-English gated-pipeline advisory

    # CHANGE_MANAGEMENT facts (populated for category=MAINTENANCE).
    is_production = Column(Boolean, nullable=True)
    implementer = Column(String(128), nullable=True)
    approver = Column(String(128), nullable=True)
    change_ticket = Column(String(64), nullable=True)

    # INCIDENT_POSTMORTEM facts (populated for category=SAFETY).
    root_cause = Column(Text, nullable=True)
    action_items = Column(Text, nullable=True)  # newline-separated

    # BACKUP_RETENTION facts (populated for category=DECOMMISSION).
    backup_verified = Column(Boolean, nullable=True)
    record_age_days = Column(Float, nullable=True)
    retention_days = Column(Float, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    resolved_at = Column(DateTime(timezone=True), nullable=True)
