"""
KAEOS HR Vertical — Time & Attendance
Function 10: Time & Attendance
"""
from sqlalchemy import Column, String, Float, DateTime, Boolean, ForeignKey, Enum, Date
from sqlalchemy.sql import func
import uuid
import enum

from app.models.domain import Base

def _uuid():
    return str(uuid.uuid4())

class LeaveType(str, enum.Enum):
    PTO = "PTO"
    SICK = "SICK"
    MATERNITY = "MATERNITY"
    PATERNITY = "PATERNITY"
    BEREAVEMENT = "BEREAVEMENT"
    JURY_DUTY = "JURY_DUTY"
    UNPAID = "UNPAID"

class LeaveStatus(str, enum.Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    CANCELLED = "CANCELLED"

class TimeOffRequest(Base):
    """Employee time off tracking."""
    __tablename__ = "hr_time_off_requests"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    employee_id = Column(String, ForeignKey("hr_employees.id"), nullable=False)
    approver_id = Column(String, ForeignKey("hr_employees.id"), nullable=True)
    
    leave_type = Column(Enum(LeaveType), default=LeaveType.PTO)
    status = Column(Enum(LeaveStatus), default=LeaveStatus.REQUESTED)
    
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    hours_requested = Column(Float, nullable=False)
    
    reason = Column(String(512), nullable=True)
    
    # Auto-Approval
    ai_auto_approved = Column(Boolean, default=False)
    ai_decision_reason = Column(String(256), nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Timesheet(Base):
    __tablename__ = "hr_timesheets"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    employee_id = Column(String, ForeignKey("hr_employees.id"), nullable=False)
    
    period_start = Column(Date, nullable=False)
    period_end = Column(Date, nullable=False)
    
    total_regular_hours = Column(Float, default=0.0)
    total_overtime_hours = Column(Float, default=0.0)
    
    status = Column(String(32), default="DRAFT") # DRAFT, SUBMITTED, APPROVED, PROCESSED
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
