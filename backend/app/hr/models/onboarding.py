"""
KAEOS HR Vertical — Onboarding Models
Function 3: Onboarding & Function 14: Offboarding
"""
from sqlalchemy import Column, String, Integer, DateTime, Boolean, JSON, ForeignKey, Enum, Text
from sqlalchemy.sql import func
import uuid
import enum

from app.models.domain import Base

def _uuid():
    return str(uuid.uuid4())

class TaskStatus(str, enum.Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    OVERDUE = "OVERDUE"
    SKIPPED = "SKIPPED"

class BoardingType(str, enum.Enum):
    ONBOARDING = "ONBOARDING"
    OFFBOARDING = "OFFBOARDING"
    CROSSBOARDING = "CROSSBOARDING" # Transfer

class BoardingPlan(Base):
    """A collection of tasks for a new hire or exiting employee."""
    __tablename__ = "hr_boarding_plans"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    employee_id = Column(String, ForeignKey("hr_employees.id"), nullable=False, index=True)
    
    plan_type = Column(Enum(BoardingType), default=BoardingType.ONBOARDING)
    status = Column(String(32), default="ACTIVE") # ACTIVE, COMPLETED, CANCELLED
    
    # Progress
    total_tasks = Column(Integer, default=0)
    completed_tasks = Column(Integer, default=0)
    
    start_date = Column(DateTime(timezone=True), nullable=False)
    target_completion_date = Column(DateTime(timezone=True), nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class BoardingTask(Base):
    __tablename__ = "hr_boarding_tasks"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    plan_id = Column(String, ForeignKey("hr_boarding_plans.id"), nullable=False)
    
    title = Column(String(256), nullable=False)
    description = Column(Text, nullable=True)
    
    # Assignment
    assignee_id = Column(String, ForeignKey("hr_employees.id"), nullable=True) # E.g., IT, Manager, or the new hire
    agent_assignee = Column(String(64), nullable=True) # If an AI agent is responsible (e.g., "IT_Provisioning_Agent")
    
    status = Column(Enum(TaskStatus), default=TaskStatus.PENDING)
    due_date = Column(DateTime(timezone=True), nullable=False)
    
    # Automation
    is_automated = Column(Boolean, default=False)
    automation_action = Column(String(128), nullable=True) # E.g., "provision_google_workspace"
    automation_result = Column(JSON, nullable=True)
    
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
