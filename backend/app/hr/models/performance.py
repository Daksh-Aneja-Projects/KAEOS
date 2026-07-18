"""
KAEOS HR Vertical — Performance Management
Function 6: Performance Management
"""
from sqlalchemy import Column, String, Integer, DateTime, Boolean, JSON, ForeignKey, Text
from sqlalchemy.sql import func
import uuid

from app.models.domain import Base

def _uuid():
    return str(uuid.uuid4())

class ReviewCycle(Base):
    __tablename__ = "hr_performance_cycles"
    
    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    
    name = Column(String(128), nullable=False) # e.g., "Q3 2026 Review"
    start_date = Column(DateTime(timezone=True), nullable=False)
    end_date = Column(DateTime(timezone=True), nullable=False)
    
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class PerformanceReview(Base):
    __tablename__ = "hr_performance_reviews"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    cycle_id = Column(String, ForeignKey("hr_performance_cycles.id"), nullable=False)
    employee_id = Column(String, ForeignKey("hr_employees.id"), nullable=False)
    reviewer_id = Column(String, ForeignKey("hr_employees.id"), nullable=False) # usually manager
    
    # Self Assessment
    self_assessment = Column(Text, nullable=True)
    self_rating = Column(Integer, nullable=True)
    
    # Manager Assessment
    manager_assessment = Column(Text, nullable=True)
    manager_rating = Column(Integer, nullable=True) # 1-5 scale
    
    # AI Summary
    ai_feedback_summary = Column(Text, nullable=True) # Aggregated from 360 feedback
    ai_growth_areas = Column(JSON, default=list)
    
    status = Column(String(32), default="DRAFT") # DRAFT, PENDING_EMPLOYEE, PENDING_MANAGER, COMPLETED
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
