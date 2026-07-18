"""
KAEOS HR Vertical — Benefits Models
Function 4: Benefits Administration
"""
from sqlalchemy import Column, String, Float, DateTime, Boolean, JSON, ForeignKey, Enum, Date
from sqlalchemy.sql import func
import uuid
import enum

from app.models.domain import Base

def _uuid():
    return str(uuid.uuid4())

class BenefitType(str, enum.Enum):
    HEALTH = "HEALTH"
    DENTAL = "DENTAL"
    VISION = "VISION"
    LIFE_INSURANCE = "LIFE_INSURANCE"
    RETIREMENT = "RETIREMENT" # 401k
    FSA_HSA = "FSA_HSA"
    PERKS = "PERKS"

class BenefitPlan(Base):
    """Available benefit plans provided by the company."""
    __tablename__ = "hr_benefit_plans"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    
    name = Column(String(128), nullable=False)
    provider = Column(String(128), nullable=False)
    benefit_type = Column(Enum(BenefitType), nullable=False)
    
    description = Column(String(512), nullable=True)
    coverage_details = Column(JSON, default=dict)
    
    # Costs (Monthly)
    employee_cost_individual = Column(Float, default=0.0)
    employee_cost_family = Column(Float, default=0.0)
    employer_contribution = Column(Float, default=0.0)
    
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class EnrollmentStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    PENDING = "PENDING"
    WAIVED = "WAIVED"
    TERMINATED = "TERMINATED"

class BenefitEnrollment(Base):
    """An employee's enrollment in a specific plan."""
    __tablename__ = "hr_benefit_enrollments"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    employee_id = Column(String, ForeignKey("hr_employees.id"), nullable=False)
    plan_id = Column(String, ForeignKey("hr_benefit_plans.id"), nullable=False)
    
    status = Column(Enum(EnrollmentStatus), default=EnrollmentStatus.PENDING)
    coverage_level = Column(String(32), default="INDIVIDUAL") # INDIVIDUAL, INDIVIDUAL_PLUS_ONE, FAMILY
    
    # Dependent tracking
    covered_dependents = Column(JSON, default=list) # list of dependent IDs or names
    
    effective_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=True)
    
    # Auto-resolved by Agent
    agent_verified = Column(Boolean, default=False)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
