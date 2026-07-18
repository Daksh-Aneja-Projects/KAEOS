"""
KAEOS Sales Domain — Commission Models
"""
from sqlalchemy import Column, String, DateTime, ForeignKey, Numeric, Float, Boolean
from sqlalchemy.sql import func
import uuid

from app.models.domain import Base

def _uuid():
    return str(uuid.uuid4())

class CommissionPlan(Base):
    """Compensation plans describing base quotas, OTE, and commission rates."""
    __tablename__ = "sls_commission_plans"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)

    plan_name = Column(String(128), nullable=False)
    rep_id = Column(String, ForeignKey("sls_reps.id"), nullable=False, index=True)
    
    base_salary = Column(Numeric(18, 2), default=0)
    ote_target = Column(Numeric(18, 2), default=0) # On Target Earnings
    base_commission_rate = Column(Float, default=10.00) # Percentage (e.g. 10%)
    accelerator_threshold = Column(Float, default=100.00) # Quota attainment % before accelerators trigger
    accelerator_rate = Column(Float, default=15.00)

    is_active = Column(Boolean, default=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

class CommissionCalculation(Base):
    """Calculated payouts for closed-won opportunities."""
    __tablename__ = "sls_commission_calculations"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    plan_id = Column(String, ForeignKey("sls_commission_plans.id"), nullable=False)
    opportunity_id = Column(String, nullable=False) # Opportunity ID string

    deal_value = Column(Numeric(18, 2), nullable=False)
    calculated_payout = Column(Numeric(18, 2), nullable=False)
    is_approved = Column(Boolean, default=False)
    paid_date = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
