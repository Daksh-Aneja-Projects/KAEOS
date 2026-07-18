"""
KAEOS Operations Domain — Quality Models
"""
from sqlalchemy import Column, String, DateTime, Enum, ForeignKey, Text
from sqlalchemy.sql import func
import uuid
import enum

from app.models.domain import Base

def _uuid():
    return str(uuid.uuid4())

class QualityStatus(str, enum.Enum):
    PASSED = "PASSED"
    FAILED = "FAILED"
    WARNING = "WARNING"
    IN_PROGRESS = "IN_PROGRESS"

class QualityStandard(Base):
    """Quality standards (e.g. ISO-9001 Section 8, SOC2 Security Rule 3)."""
    __tablename__ = "ops_quality_standards"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)

    name = Column(String(256), nullable=False)
    description = Column(String(512), nullable=True)
    regulatory_framework = Column(String(64), nullable=True) # ISO-9001, SOC2

    created_at = Column(DateTime(timezone=True), server_default=func.now())

class Inspection(Base):
    """Quality inspections completed on operational processes."""
    __tablename__ = "ops_inspections"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    standard_id = Column(String, ForeignKey("ops_quality_standards.id"), nullable=False, index=True)

    inspected_item = Column(String(256), nullable=False)
    inspector = Column(String(128), nullable=False)
    
    status = Column(Enum(QualityStatus), default=QualityStatus.IN_PROGRESS)
    notes = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

class NonConformance(Base):
    """Failures/defect logs documenting breaches of quality standards."""
    __tablename__ = "ops_non_conformance_logs"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    inspection_id = Column(String, ForeignKey("ops_inspections.id"), nullable=False, index=True)

    defect_description = Column(Text, nullable=False)
    impact_rating = Column(String(32), default="MEDIUM") # LOW, MEDIUM, HIGH
    corrective_action_plan = Column(Text, nullable=True)
    is_closed = Column(Text, default="No")

    created_at = Column(DateTime(timezone=True), server_default=func.now())
