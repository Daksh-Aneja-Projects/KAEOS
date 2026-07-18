"""
KAEOS Legal Domain — Regulatory & Compliance Models
"""
from sqlalchemy import Column, String, DateTime, Text, Date, ForeignKey, Numeric, Enum, Integer
from sqlalchemy.sql import func
import uuid
import enum

from app.models.domain import Base

def _uuid():
    return str(uuid.uuid4())

class ObligationStatus(str, enum.Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    OVERDUE = "OVERDUE"
    WAIVED = "WAIVED"

class RegulatoryRequirement(Base):
    """External regulations impacting corporate entity (e.g. GDPR Art 30, SOC2 Trust Services Criteria)."""
    __tablename__ = "leg_regulatory_requirements"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)

    regulation = Column(String(128), nullable=False) # e.g., "GDPR", "SOC2", "HIPAA"
    section = Column(String(64), nullable=False)    # e.g., "Art. 32", "CC.6.1"
    title = Column(String(256), nullable=False)
    description = Column(Text, nullable=True)
    jurisdiction = Column(String(64), default="Federal")

    created_at = Column(DateTime(timezone=True), server_default=func.now())

class ComplianceObligation(Base):
    """Specific recurring or one-time compliance actions mapped to legal/operational owners."""
    __tablename__ = "leg_compliance_obligations"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    requirement_id = Column(String, ForeignKey("leg_regulatory_requirements.id"), nullable=True)

    title = Column(String(256), nullable=False)
    description = Column(Text, nullable=True)
    owner = Column(String(128), nullable=True)
    
    due_date = Column(Date, nullable=True)
    status = Column(Enum(ObligationStatus), default=ObligationStatus.PENDING)
    evidence_path = Column(String(512), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

class ComplianceAssessment(Base):
    """Audit assessments evaluating operational controls against compliance frameworks."""
    __tablename__ = "leg_compliance_assessments"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)

    framework = Column(String(64), nullable=False)  # SOC2, ISO-27001, GDPR
    assessment_date = Column(Date, nullable=False)
    assessor = Column(String(128), nullable=False)
    
    score = Column(Numeric(5, 2), nullable=True)
    findings_count = Column(Integer, default=0)
    report_path = Column(String(512), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
