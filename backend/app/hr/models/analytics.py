"""
KAEOS HR Vertical — Analytics
Function 13: HR Analytics & Insights
"""
from sqlalchemy import Column, String, Integer, Float, DateTime, JSON, Date
from sqlalchemy.sql import func
import uuid

from app.models.domain import Base

def _uuid():
    return str(uuid.uuid4())

class HRMetricSnapshot(Base):
    """Daily snapshot of key HR metrics for analytics dashboards."""
    __tablename__ = "hr_metric_snapshots"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    
    snapshot_date = Column(Date, nullable=False)
    
    # Headcount Metrics
    total_headcount = Column(Integer, default=0)
    active_contractors = Column(Integer, default=0)
    voluntary_turnover_ytd = Column(Float, default=0.0) # Percentage
    involuntary_turnover_ytd = Column(Float, default=0.0)
    
    # Recruiting Metrics
    open_requisitions = Column(Integer, default=0)
    time_to_fill_avg_days = Column(Float, default=0.0)
    offer_acceptance_rate = Column(Float, default=0.0)
    
    # Diversity (Aggregated to protect PII)
    diversity_metrics = Column(JSON, default=dict)
    
    # Financial
    total_payroll_run_rate = Column(Float, default=0.0)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
