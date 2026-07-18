"""
KAEOS HR Vertical — Compliance & Reporting
Function 12: Compliance
"""
from sqlalchemy import Column, String, Integer, DateTime, Boolean, JSON, Enum
from sqlalchemy.sql import func
import uuid
import enum

from app.models.domain import Base

def _uuid():
    return str(uuid.uuid4())

class ComplianceFramework(str, enum.Enum):
    EEOC = "EEOC"
    OSHA = "OSHA"
    HIPAA = "HIPAA"
    I9 = "I9"
    GDPR = "GDPR"
    ACA = "ACA"

class ComplianceReport(Base):
    """Automatically generated compliance reports."""
    __tablename__ = "hr_compliance_reports"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    
    framework = Column(Enum(ComplianceFramework), nullable=False)
    report_name = Column(String(256), nullable=False) # e.g., "EEO-1 Component 1"
    
    period_year = Column(Integer, nullable=False)
    
    status = Column(String(32), default="GENERATED") # GENERATED, REVIEWED, SUBMITTED
    data = Column(JSON, nullable=False) # The actual report data
    
    generated_at = Column(DateTime(timezone=True), server_default=func.now())
    submitted_at = Column(DateTime(timezone=True), nullable=True)
    
class ComplianceViolation(Base):
    """Recorded violations detected by the ComplianceEngine."""
    __tablename__ = "hr_compliance_violations"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    
    framework = Column(String(64), nullable=False)
    severity = Column(String(32), nullable=False) # WARNING, BLOCKER
    description = Column(String(512), nullable=False)
    
    context = Column(JSON, nullable=True) # What caused it
    actor_id = Column(String, nullable=True) # Agent or User who caused it
    
    resolved = Column(Boolean, default=False)
    resolution_notes = Column(String(512), nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
