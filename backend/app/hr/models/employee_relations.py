"""
KAEOS HR Vertical — Employee Relations
Function 8: Employee Relations
"""
from sqlalchemy import Column, String, DateTime, JSON, ForeignKey, Enum, Text
from sqlalchemy.sql import func
import uuid
import enum

from app.models.domain import Base

def _uuid():
    return str(uuid.uuid4())

class CaseStatus(str, enum.Enum):
    OPEN = "OPEN"
    UNDER_INVESTIGATION = "UNDER_INVESTIGATION"
    PENDING_ACTION = "PENDING_ACTION"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"

class CaseSeverity(str, enum.Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"

class ERCase(Base):
    """Employee relations case or investigation."""
    __tablename__ = "hr_er_cases"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    
    title = Column(String(256), nullable=False)
    description = Column(Text, nullable=False)
    
    reporter_id = Column(String, ForeignKey("hr_employees.id"), nullable=True) # Can be anonymous
    accused_id = Column(String, ForeignKey("hr_employees.id"), nullable=True)
    investigator_id = Column(String, ForeignKey("hr_employees.id"), nullable=True)
    
    category = Column(String(64), nullable=False) # e.g., "HARASSMENT", "POLICY_VIOLATION", "DISPUTE"
    status = Column(Enum(CaseStatus), default=CaseStatus.OPEN)
    severity = Column(Enum(CaseSeverity), default=CaseSeverity.MEDIUM)
    
    # AI Assistance
    ai_risk_assessment = Column(Text, nullable=True)
    ai_recommended_actions = Column(JSON, default=list)
    
    # Audit Trail
    resolution_notes = Column(Text, nullable=True)
    
    opened_at = Column(DateTime(timezone=True), server_default=func.now())
    closed_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
