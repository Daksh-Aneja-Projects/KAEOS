"""
KAEOS Sales Domain — Forecasting Models
"""
from sqlalchemy import Column, String, DateTime, ForeignKey, Numeric
from sqlalchemy.sql import func
import uuid

from app.models.domain import Base

def _uuid():
    return str(uuid.uuid4())

class SalesForecast(Base):
    """Aggregate sales forecasts for a given fiscal quarter."""
    __tablename__ = "sls_forecasts"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)

    quarter = Column(String(16), nullable=False) # e.g. "Q3-2026"
    target_quota = Column(Numeric(18, 2), default=0)
    
    commit_amount = Column(Numeric(18, 2), default=0) # Best-estimate commit
    best_case_amount = Column(Numeric(18, 2), default=0)
    pipeline_amount = Column(Numeric(18, 2), default=0)
    
    ai_predicted_amount = Column(Numeric(18, 2), default=0)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

class ForecastLine(Base):
    """Rep-level forecasting commits composing the overall team forecast."""
    __tablename__ = "sls_forecast_lines"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    forecast_id = Column(String, ForeignKey("sls_forecasts.id"), nullable=False, index=True)
    rep_id = Column(String, ForeignKey("sls_reps.id"), nullable=False)

    commit_amount = Column(Numeric(18, 2), default=0)
    best_case_amount = Column(Numeric(18, 2), default=0)
    pipeline_amount = Column(Numeric(18, 2), default=0)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
