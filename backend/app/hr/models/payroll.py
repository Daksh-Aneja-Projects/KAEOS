"""
KAEOS HR Vertical — Payroll
Function 11: Payroll Processing
"""
from sqlalchemy import Column, String, Float, DateTime, Boolean, JSON, ForeignKey, Enum, Date
from sqlalchemy.sql import func
import uuid
import enum

from app.models.domain import Base

def _uuid():
    return str(uuid.uuid4())

class PayrollRunStatus(str, enum.Enum):
    PREP = "PREP"
    PROCESSING = "PROCESSING"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"

class PayrollRun(Base):
    """A specific execution of payroll for a time period."""
    __tablename__ = "hr_payroll_runs"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    
    period_start = Column(Date, nullable=False)
    period_end = Column(Date, nullable=False)
    pay_date = Column(Date, nullable=False)
    
    status = Column(Enum(PayrollRunStatus), default=PayrollRunStatus.PREP)
    
    # Aggregated Financials
    total_gross = Column(Float, default=0.0)
    total_net = Column(Float, default=0.0)
    total_taxes = Column(Float, default=0.0)
    total_deductions = Column(Float, default=0.0)
    
    # Auto-Calculated by Agent
    ai_anomalies_detected = Column(JSON, default=list)
    ai_approved = Column(Boolean, default=False)
    
    approved_by_id = Column(String, ForeignKey("hr_employees.id"), nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

class Payslip(Base):
    __tablename__ = "hr_payslips"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    run_id = Column(String, ForeignKey("hr_payroll_runs.id"), nullable=False)
    employee_id = Column(String, ForeignKey("hr_employees.id"), nullable=False)
    
    gross_pay = Column(Float, default=0.0)
    net_pay = Column(Float, default=0.0)
    taxes = Column(JSON, default=dict)
    deductions = Column(JSON, default=dict)
    
    document_uri = Column(String(512), nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
