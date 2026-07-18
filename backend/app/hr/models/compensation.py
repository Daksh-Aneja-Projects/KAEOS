"""
KAEOS HR Vertical — Compensation Models
Function 5: Compensation & Equity
"""
from sqlalchemy import Column, String, Integer, Float, DateTime, Boolean, ForeignKey, Enum, Date
from sqlalchemy.sql import func
import uuid
import enum

from app.models.domain import Base

def _uuid():
    return str(uuid.uuid4())

class CompType(str, enum.Enum):
    SALARY = "SALARY"
    HOURLY = "HOURLY"
    COMMISSION = "COMMISSION"
    BONUS = "BONUS"
    EQUITY = "EQUITY"

class Compensation(Base):
    """An employee's current or historical compensation package."""
    __tablename__ = "hr_compensation"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    employee_id = Column(String, ForeignKey("hr_employees.id"), nullable=False, index=True)
    
    comp_type = Column(Enum(CompType), default=CompType.SALARY)
    base_amount = Column(Float, nullable=False)
    currency = Column(String(3), default="USD")
    
    # Bonuses/Variables
    target_bonus_pct = Column(Float, default=0.0)
    
    # Equity
    equity_grant = Column(Integer, default=0) # Number of shares/options
    equity_type = Column(String(16), nullable=True) # ISO, NSO, RSU
    vesting_schedule = Column(String(64), nullable=True)
    
    # Schedule
    effective_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=True) # If null, this is current
    is_current = Column(Boolean, default=True)
    
    # Reason for change
    change_reason = Column(String(128), nullable=True) # e.g., "Promotion", "Merit Cycle", "New Hire"
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
