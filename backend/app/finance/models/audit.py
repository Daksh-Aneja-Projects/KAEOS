"""
KAEOS Finance Domain — Audit Models
Internal audit trails, findings, and control testing.
"""
from sqlalchemy import Column, String, Integer, DateTime, Boolean, JSON, ForeignKey, Enum, Date, Text, Numeric
from sqlalchemy.sql import func
import uuid
import enum

from app.models.domain import Base

def _uuid():
    return str(uuid.uuid4())


class AuditTrail(Base):
    """Immutable audit log of all financial transactions and changes."""
    __tablename__ = "fin_audit_trail"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)

    event_type = Column(String(32), nullable=False)          # CREATE, UPDATE, DELETE, APPROVE, POST, VOID
    entity_type = Column(String(64), nullable=False)         # "Invoice", "JournalEntry", "Payment"
    entity_id = Column(String, nullable=False)
    entity_description = Column(String(256), nullable=True)

    # Change details
    field_changed = Column(String(64), nullable=True)
    old_value = Column(Text, nullable=True)
    new_value = Column(Text, nullable=True)
    changes_json = Column(JSON, default=dict)                # Full diff for complex changes

    # Actor
    performed_by = Column(String, nullable=False)            # User ID or "SYSTEM" or "AI_AGENT"
    performed_by_type = Column(String(16), default="USER")   # USER, SYSTEM, AI_AGENT
    ip_address = Column(String(45), nullable=True)

    # Integrity
    checksum = Column(String(64), nullable=True)             # SHA-256 hash for tamper detection
    previous_checksum = Column(String(64), nullable=True)    # Chain link

    timestamp = Column(DateTime(timezone=True), server_default=func.now())


class FindingSeverity(str, enum.Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFORMATIONAL = "INFORMATIONAL"


class FindingStatus(str, enum.Enum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    REMEDIATED = "REMEDIATED"
    RISK_ACCEPTED = "RISK_ACCEPTED"
    CLOSED = "CLOSED"


class AuditFinding(Base):
    """Audit findings from internal or external audits."""
    __tablename__ = "fin_audit_findings"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)

    finding_number = Column(String(32), nullable=False, unique=True)
    title = Column(String(256), nullable=False)
    description = Column(Text, nullable=False)
    severity = Column(Enum(FindingSeverity), nullable=False)
    status = Column(Enum(FindingStatus), default=FindingStatus.OPEN)

    # Classification
    audit_type = Column(String(32), default="INTERNAL")      # INTERNAL, EXTERNAL, SOX
    control_id = Column(String, ForeignKey("fin_sox_controls.id"), nullable=True)
    area = Column(String(64), nullable=True)                 # "AP", "AR", "GL", "Payroll"

    # Impact
    financial_impact = Column(Numeric(18, 2), nullable=True)
    risk_rating = Column(String(16), nullable=True)

    # Remediation
    remediation_plan = Column(Text, nullable=True)
    remediation_owner = Column(String, nullable=True)
    target_remediation_date = Column(Date, nullable=True)
    actual_remediation_date = Column(Date, nullable=True)

    # AI
    ai_detected = Column(Boolean, default=False)             # Was this found by AI?
    ai_recommendation = Column(Text, nullable=True)

    identified_by = Column(String, nullable=True)
    identified_date = Column(Date, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ControlTestResult(str, enum.Enum):
    EFFECTIVE = "EFFECTIVE"
    PARTIALLY_EFFECTIVE = "PARTIALLY_EFFECTIVE"
    INEFFECTIVE = "INEFFECTIVE"
    NOT_TESTED = "NOT_TESTED"


class ControlTest(Base):
    """SOX control testing records."""
    __tablename__ = "fin_control_tests"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    control_id = Column(String, ForeignKey("fin_sox_controls.id"), nullable=False, index=True)

    test_date = Column(Date, nullable=False)
    tester = Column(String, nullable=False)
    test_procedure = Column(Text, nullable=True)
    sample_size = Column(Integer, nullable=True)
    exceptions_found = Column(Integer, default=0)

    result = Column(Enum(ControlTestResult), default=ControlTestResult.NOT_TESTED)
    conclusion = Column(Text, nullable=True)
    evidence_path = Column(String(512), nullable=True)       # GCS/S3 for workpapers

    # AI-assisted testing
    ai_assisted = Column(Boolean, default=False)
    ai_test_summary = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
