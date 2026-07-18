"""
KAEOS Finance Domain — Compliance Models
Financial compliance rules, SOX controls, and regulatory tracking.
"""
from sqlalchemy import Column, String, Float, DateTime, Boolean, JSON, Enum, Date, Text
from sqlalchemy.sql import func
import uuid
import enum

from app.models.domain import Base

def _uuid():
    return str(uuid.uuid4())


class FinanceComplianceRule(Base):
    """Regulatory compliance rules applicable to financial operations."""
    __tablename__ = "fin_compliance_rules"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)

    regulation = Column(String(32), nullable=False)          # SOX, GAAP, IFRS, SOC2, PCI-DSS
    section = Column(String(32), nullable=True)              # e.g., "302", "404"
    name = Column(String(256), nullable=False)
    description = Column(Text, nullable=False)

    # Applicability
    applies_to = Column(JSON, default=list)                  # ["AP", "AR", "GL", "PAYROLL"]
    jurisdiction = Column(String(64), default="US")
    effective_date = Column(Date, nullable=True)

    # Enforcement
    is_blocking = Column(Boolean, default=False)             # If true, blocks transactions that violate
    severity = Column(String(16), default="MEDIUM")          # CRITICAL, HIGH, MEDIUM, LOW
    auto_check_enabled = Column(Boolean, default=True)

    # Status
    is_active = Column(Boolean, default=True)
    last_reviewed = Column(Date, nullable=True)
    reviewed_by = Column(String, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class SOXControlStatus(str, enum.Enum):
    EFFECTIVE = "EFFECTIVE"
    NEEDS_IMPROVEMENT = "NEEDS_IMPROVEMENT"
    INEFFECTIVE = "INEFFECTIVE"
    NOT_ASSESSED = "NOT_ASSESSED"


class SOXControl(Base):
    """SOX Section 404 internal controls over financial reporting (ICFR)."""
    __tablename__ = "fin_sox_controls"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)

    control_id_code = Column(String(32), nullable=False, unique=True)  # e.g., "CTRL-AP-001"
    name = Column(String(256), nullable=False)
    description = Column(Text, nullable=False)
    objective = Column(Text, nullable=True)

    # Classification
    control_type = Column(String(16), default="PREVENTIVE")  # PREVENTIVE, DETECTIVE, CORRECTIVE
    frequency = Column(String(16), default="CONTINUOUS")     # CONTINUOUS, DAILY, MONTHLY, QUARTERLY, ANNUAL
    nature = Column(String(16), default="AUTOMATED")         # AUTOMATED, MANUAL, IT_DEPENDENT
    area = Column(String(64), nullable=True)                 # "AP", "AR", "GL", "Close", "Payroll"

    # Risk
    risk_level = Column(String(16), default="MEDIUM")
    financial_statement_assertion = Column(JSON, default=list)  # ["Completeness", "Accuracy", "Existence"]

    # Assessment
    status = Column(Enum(SOXControlStatus), default=SOXControlStatus.NOT_ASSESSED)
    last_test_date = Column(Date, nullable=True)
    last_test_result = Column(String(32), nullable=True)
    next_test_date = Column(Date, nullable=True)

    # Ownership
    control_owner = Column(String, nullable=True)
    process_owner = Column(String, nullable=True)

    # AI monitoring
    ai_monitored = Column(Boolean, default=False)
    ai_effectiveness_score = Column(Float, nullable=True)    # 0-100

    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
