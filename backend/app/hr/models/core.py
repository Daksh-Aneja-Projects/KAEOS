"""
KAEOS HR Vertical — Core Employee Models
Function 1: Employee Data & Profiles
"""
from sqlalchemy import Column, String, DateTime, Boolean, JSON, ForeignKey, Enum, Date
from sqlalchemy.sql import func
import uuid
import enum

from app.models.domain import Base

def _uuid():
    return str(uuid.uuid4())

class EmploymentStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    ONBOARDING = "ONBOARDING"
    LEAVE = "LEAVE"
    TERMINATED = "TERMINATED"
    CONTRACTOR = "CONTRACTOR"

class HREmployee(Base):
    __tablename__ = "hr_employees"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    department_id = Column(String, ForeignKey("departments.id"), nullable=True) # Logical KAEOS department
    
    # Identity
    worker_id = Column(String(64), nullable=True, unique=True) # HRIS ID
    first_name = Column(String(64), nullable=False)
    last_name = Column(String(64), nullable=False)
    email = Column(String(128), nullable=False, unique=True)
    personal_email = Column(String(128), nullable=True)
    phone = Column(String(32), nullable=True)
    
    # Employment details
    status = Column(Enum(EmploymentStatus), default=EmploymentStatus.ACTIVE)
    hire_date = Column(Date, nullable=False)
    termination_date = Column(Date, nullable=True)
    
    # Org Position
    job_title = Column(String(128), nullable=False)
    manager_id = Column(String, ForeignKey("hr_employees.id"), nullable=True)
    cost_center = Column(String(64), nullable=True)
    location = Column(String(64), nullable=True)
    is_remote = Column(Boolean, default=False)
    
    # Agent Context (how agents should interact with them)
    communication_preferences = Column(JSON, default=dict) # Slack vs Email, preferred hours
    accessibility_needs = Column(JSON, default=dict)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class DocumentType(str, enum.Enum):
    I9 = "I9"
    W4 = "W4"
    OFFER_LETTER = "OFFER_LETTER"
    HANDBOOK_ACK = "HANDBOOK_ACK"
    PERFORMANCE_REVIEW = "PERFORMANCE_REVIEW"
    DISCIPLINARY = "DISCIPLINARY"
    OTHER = "OTHER"

class EmployeeDocument(Base):
    __tablename__ = "hr_employee_documents"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    employee_id = Column(String, ForeignKey("hr_employees.id"), nullable=False, index=True)
    
    doc_type = Column(Enum(DocumentType), nullable=False)
    title = Column(String(128), nullable=False)
    file_path = Column(String(512), nullable=False) # GCS or S3 URI
    
    # Security/Compliance
    is_signed = Column(Boolean, default=False)
    signature_date = Column(DateTime(timezone=True), nullable=True)
    expiration_date = Column(Date, nullable=True)
    is_pii = Column(Boolean, default=True)
    
    uploaded_at = Column(DateTime(timezone=True), server_default=func.now())
