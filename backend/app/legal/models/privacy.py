"""
KAEOS Legal Domain — Privacy & Data Protection Models
"""
from sqlalchemy import Column, String, DateTime, Text, Date, Enum, Boolean
from sqlalchemy.sql import func
import uuid
import enum

from app.models.domain import Base

def _uuid():
    return str(uuid.uuid4())

class DsarType(str, enum.Enum):
    ACCESS = "ACCESS"
    DELETE = "DELETE"
    RECTIFY = "RECTIFY"
    PORTABILITY = "PORTABILITY"
    RESTRICT = "RESTRICT"

class DsarStatus(str, enum.Enum):
    RECEIVED = "RECEIVED"
    IDENTITY_VERIFIED = "IDENTITY_VERIFIED"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"

class DataSubjectRequest(Base):
    """DSAR requests submitted under GDPR / CCPA privacy laws."""
    __tablename__ = "leg_data_subject_requests"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)

    requestor_name = Column(String(256), nullable=False)
    requestor_email = Column(String(128), nullable=False)
    
    request_type = Column(Enum(DsarType), default=DsarType.ACCESS)
    status = Column(Enum(DsarStatus), default=DsarStatus.RECEIVED)
    
    request_date = Column(Date, nullable=False)
    deadline_date = Column(Date, nullable=False)
    
    assigned_officer = Column(String(128), nullable=True)
    evidence_path = Column(String(512), nullable=True)
    ai_validation = Column(Boolean, default=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

class PrivacyImpactAssessment(Base):
    """Assessments analyzing risk factors of software applications and database tables holding PII."""
    __tablename__ = "leg_privacy_impact_assessments"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)

    system_name = Column(String(256), nullable=False)
    pii_elements = Column(Text, nullable=True)  # JSON or comma-separated list of items (name, email, SSN)
    
    risk_rating = Column(String(32), default="MEDIUM") # LOW, MEDIUM, HIGH
    remediation_required = Column(Boolean, default=False)
    status = Column(String(32), default="DRAFT") # DRAFT, SIGNED_OFF
    
    signoff_date = Column(Date, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

class DataProcessingRecord(Base):
    """Records of Processing Activities (ROPA) under GDPR Art 30."""
    __tablename__ = "leg_ropa_records"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)

    data_controller = Column(String(256), nullable=False)
    purpose_of_processing = Column(Text, nullable=False)
    categories_of_subjects = Column(Text, nullable=True) # Employees, Customers, Leads
    categories_of_recipients = Column(Text, nullable=True) # Third-party processors, cloud hosting
    
    retention_period = Column(String(128), nullable=True)
    security_measures = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
