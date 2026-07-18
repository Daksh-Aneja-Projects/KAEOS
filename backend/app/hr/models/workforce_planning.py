"""
KAEOS HR Vertical — Workforce Planning
Function 9: Workforce Planning & Org Design
"""
from sqlalchemy import Column, String, Integer, Float, DateTime, JSON, Enum
from sqlalchemy.sql import func
import uuid
import enum

from app.models.domain import Base

def _uuid():
    return str(uuid.uuid4())

class PlanStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"

class HeadcountPlan(Base):
    """Strategic plan for headcount changes."""
    __tablename__ = "hr_headcount_plans"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    
    name = Column(String(256), nullable=False) # E.g., "FY27 Engineering Scaling"
    department_id = Column(String, nullable=True)
    
    target_year = Column(Integer, nullable=False)
    budget_allocated = Column(Float, default=0.0)
    currency = Column(String(3), default="USD")
    
    status = Column(Enum(PlanStatus), default=PlanStatus.DRAFT)
    
    # Details of positions to add/remove
    planned_positions = Column(JSON, default=list)
    # Schema: [{"title": "Senior Engineer", "count": 5, "target_qtr": "Q2", "est_salary": 150000}]
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
