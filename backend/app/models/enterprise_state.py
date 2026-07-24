"""
KAEOS Enterprise State Engine Models
Continuously updated point-in-time representations of department state.
Used by the Reasoning Engine to make decisions based on the current reality.
"""

from datetime import datetime, timezone
import uuid

from sqlalchemy import String, DateTime, Float, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class FinanceState(Base):
    """
    Real-time representation of Enterprise Financial State.
    """
    __tablename__ = "es_finance_state"
    
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String, index=True)  # append-only time-series: many snapshots per tenant (get_state picks latest)
    
    total_cash: Mapped[float] = mapped_column(Float, default=0.0)
    burn_rate: Mapped[float] = mapped_column(Float, default=0.0)
    runway_months: Mapped[float] = mapped_column(Float, default=0.0)
    
    arr: Mapped[float] = mapped_column(Float, default=0.0) # Annual Recurring Revenue
    mrr: Mapped[float] = mapped_column(Float, default=0.0) # Monthly Recurring Revenue
    
    total_accounts_receivable: Mapped[float] = mapped_column(Float, default=0.0)
    total_accounts_payable: Mapped[float] = mapped_column(Float, default=0.0)
    
    financial_health_score: Mapped[float] = mapped_column(Float, default=1.0)
    
    snapshot_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class HRState(Base):
    """
    Real-time representation of Enterprise Human Resources State.
    """
    __tablename__ = "es_hr_state"
    
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String, index=True)  # append-only time-series: many snapshots per tenant
    
    total_headcount: Mapped[int] = mapped_column(Integer, default=0)
    open_requisitions: Mapped[int] = mapped_column(Integer, default=0)
    
    attrition_rate: Mapped[float] = mapped_column(Float, default=0.0)
    offer_acceptance_rate: Mapped[float] = mapped_column(Float, default=0.0)
    
    employee_nps: Mapped[float] = mapped_column(Float, default=0.0) # Employee Net Promoter Score
    
    hr_health_score: Mapped[float] = mapped_column(Float, default=1.0)
    
    snapshot_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class OpsState(Base):
    """
    Real-time representation of Operational State.
    """
    __tablename__ = "es_ops_state"
    
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String, index=True)  # append-only time-series: many snapshots per tenant
    
    active_projects: Mapped[int] = mapped_column(Integer, default=0)
    projects_at_risk: Mapped[int] = mapped_column(Integer, default=0)
    
    vendor_incidents: Mapped[int] = mapped_column(Integer, default=0)
    supply_chain_health: Mapped[float] = mapped_column(Float, default=1.0)
    
    ops_health_score: Mapped[float] = mapped_column(Float, default=1.0)
    
    snapshot_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class ITState(Base):
    """
    Real-time representation of IT / Systems State.
    """
    __tablename__ = "es_it_state"
    
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String, index=True)  # append-only time-series: many snapshots per tenant
    
    system_uptime: Mapped[float] = mapped_column(Float, default=100.0)
    open_p1_incidents: Mapped[int] = mapped_column(Integer, default=0)
    open_security_vulns: Mapped[int] = mapped_column(Integer, default=0)
    
    security_score: Mapped[float] = mapped_column(Float, default=1.0)
    
    snapshot_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
