"""
KAEOS Finance Domain — Budgeting & Forecasting Models
Budget planning, line-item tracking, and AI-assisted forecasting.
"""
from sqlalchemy import Column, String, Integer, Float, DateTime, JSON, ForeignKey, Enum, Date, Text, Numeric
from sqlalchemy.sql import func
import uuid
import enum

from app.models.domain import Base

def _uuid():
    return str(uuid.uuid4())


class BudgetStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
    REVISED = "REVISED"


class Budget(Base):
    """Annual or project-level budget."""
    __tablename__ = "fin_budgets"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)

    name = Column(String(128), nullable=False)
    budget_type = Column(String(32), default="OPERATING")    # OPERATING, CAPITAL, PROJECT
    fiscal_year = Column(Integer, nullable=False)
    department = Column(String(64), nullable=True)
    cost_center = Column(String(64), nullable=True)

    status = Column(Enum(BudgetStatus), default=BudgetStatus.DRAFT)

    # Totals
    total_planned = Column(Numeric(18, 2), default=0)
    total_actual = Column(Numeric(18, 2), default=0)
    total_committed = Column(Numeric(18, 2), default=0)      # POs issued but not yet invoiced
    total_variance = Column(Numeric(18, 2), default=0)
    variance_pct = Column(Float, default=0)

    currency = Column(String(3), default="USD")

    # Approval
    owner_id = Column(String, nullable=True)
    approved_by = Column(String, nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)

    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class BudgetLine(Base):
    """Individual line item within a budget (per GL account per period)."""
    __tablename__ = "fin_budget_lines"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    budget_id = Column(String, ForeignKey("fin_budgets.id"), nullable=False, index=True)
    account_id = Column(String, ForeignKey("fin_chart_of_accounts.id"), nullable=True)

    category = Column(String(64), nullable=False)            # e.g., "Personnel", "Software", "Travel"
    period = Column(Integer, nullable=False)                  # 1-12
    period_label = Column(String(16), nullable=True)          # "Jan", "Q1", etc.

    planned_amount = Column(Numeric(18, 2), default=0)
    actual_amount = Column(Numeric(18, 2), default=0)
    committed_amount = Column(Numeric(18, 2), default=0)
    variance = Column(Numeric(18, 2), default=0)

    notes = Column(String(256), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Forecast(Base):
    """AI-generated or analyst-driven financial forecast."""
    __tablename__ = "fin_forecasts"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    budget_id = Column(String, ForeignKey("fin_budgets.id"), nullable=True)

    forecast_name = Column(String(128), nullable=False)
    forecast_type = Column(String(32), default="REVENUE")    # REVENUE, EXPENSE, CASH_FLOW
    period_start = Column(Date, nullable=False)
    period_end = Column(Date, nullable=False)
    granularity = Column(String(16), default="MONTHLY")      # WEEKLY, MONTHLY, QUARTERLY

    # Scenario modeling
    scenario = Column(String(32), default="BASE")            # BASE, OPTIMISTIC, PESSIMISTIC

    # Values
    forecast_values = Column(JSON, default=list)              # [{period, amount, confidence}]
    total_forecast = Column(Numeric(18, 2), default=0)

    # AI metadata
    model_used = Column(String(64), nullable=True)           # e.g., "linear_regression", "llm_analysis"
    confidence_score = Column(Float, nullable=True)          # 0.0-1.0
    ai_rationale = Column(Text, nullable=True)

    created_by = Column(String, nullable=True)               # "AI" or user ID
    created_at = Column(DateTime(timezone=True), server_default=func.now())
