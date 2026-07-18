"""
KAEOS Enterprise Graph Models
Maps the digital twin of the organization.
Nodes: Organization, Team, Employee, Contractor, Customer, Vendor, Asset, Project, Goal, Policy, Risk.
Edges (Relationships): Mapped via adjacency list or association tables (e.g. GraphRelationship).
"""

from typing import Optional
from datetime import datetime, timezone
import uuid

from sqlalchemy import String, DateTime, Text, Float, Boolean
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import JSONB

from app.core.database import Base

# --- Enterprise Graph Edges ---

class GraphRelationship(Base):
    """
    Universal generic relationship table for the Enterprise Graph.
    Can link ANY two nodes in the system (e.g., Employee -> REPORTS_TO -> Employee, Project -> IMPACTS -> Goal)
    """
    __tablename__ = "eg_relationships"
    
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    
    source_id: Mapped[str] = mapped_column(String, index=True)
    source_type: Mapped[str] = mapped_column(String) # e.g., "Employee", "Project"
    
    target_id: Mapped[str] = mapped_column(String, index=True)
    target_type: Mapped[str] = mapped_column(String) # e.g., "Team", "Goal"
    
    relation_type: Mapped[str] = mapped_column(String, index=True) # e.g., "REPORTS_TO", "DEPENDS_ON", "MITIGATES"
    
    properties: Mapped[dict] = mapped_column(JSONB, default={})
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


# --- Enterprise Nodes ---

class Organization(Base):
    """Root node of the Enterprise Twin."""
    __tablename__ = "eg_organizations"
    
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String, index=True, unique=True)
    
    name: Mapped[str] = mapped_column(String)
    industry: Mapped[Optional[str]] = mapped_column(String)
    headquarters: Mapped[Optional[str]] = mapped_column(String)
    
    metadata_json: Mapped[dict] = mapped_column(JSONB, default={})
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class Team(Base):
    """Teams/Squads beneath Departments."""
    __tablename__ = "eg_teams"
    
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    department_id: Mapped[str] = mapped_column(String, index=True) # Links to workforce_departments
    
    name: Mapped[str] = mapped_column(String)
    description: Mapped[Optional[str]] = mapped_column(String)
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class Project(Base):
    """Business Initiatives."""
    __tablename__ = "eg_projects"
    
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    
    name: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="PLANNED") # PLANNED, ACTIVE, AT_RISK, COMPLETED, CANCELLED
    health_score: Mapped[float] = mapped_column(Float, default=1.0)
    
    budget: Mapped[Optional[float]] = mapped_column(Float)
    spend: Mapped[Optional[float]] = mapped_column(Float)
    
    start_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    end_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class Goal(Base):
    """OKRs, KPIs, and Strategic Objectives."""
    __tablename__ = "eg_goals"
    
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    
    title: Mapped[str] = mapped_column(String)
    description: Mapped[Optional[str]] = mapped_column(String)
    goal_type: Mapped[str] = mapped_column(String, default="OKR") # OKR, KPI, STRATEGIC
    
    target_value: Mapped[Optional[float]] = mapped_column(Float)
    current_value: Mapped[Optional[float]] = mapped_column(Float)
    unit: Mapped[Optional[str]] = mapped_column(String)
    
    status: Mapped[str] = mapped_column(String, default="ON_TRACK") # ON_TRACK, AT_RISK, OFF_TRACK, ACHIEVED
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class Initiative(Base):
    """Strategic Initiatives driving Goals."""
    __tablename__ = "eg_initiatives"
    
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    
    title: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="ACTIVE")
    health_score: Mapped[float] = mapped_column(Float, default=1.0)
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class StrategicProgram(Base):
    """Large scale programs containing multiple initiatives."""
    __tablename__ = "eg_strategic_programs"
    
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    
    title: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="ACTIVE")
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class Outcome(Base):
    """Business Outcomes representing achieved value."""
    __tablename__ = "eg_outcomes"
    
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    
    description: Mapped[str] = mapped_column(String)
    value_realized: Mapped[Optional[float]] = mapped_column(Float)
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class Risk(Base):
    """Enterprise Risks (Financial, Operational, Compliance, Security)."""
    __tablename__ = "eg_risks"
    
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    
    title: Mapped[str] = mapped_column(String)
    category: Mapped[str] = mapped_column(String) # FINANCE, HR, IT, LEGAL
    severity: Mapped[str] = mapped_column(String) # LOW, MEDIUM, HIGH, CRITICAL
    probability: Mapped[float] = mapped_column(Float) # 0.0 to 1.0
    impact_score: Mapped[float] = mapped_column(Float) # 0.0 to 1.0
    
    mitigation_plan: Mapped[Optional[str]] = mapped_column(Text)
    
    status: Mapped[str] = mapped_column(String, default="IDENTIFIED") # IDENTIFIED, MITIGATED, REALIZED
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class Asset(Base):
    """Physical or Digital Assets."""
    __tablename__ = "eg_assets"
    
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    
    name: Mapped[str] = mapped_column(String)
    asset_type: Mapped[str] = mapped_column(String) # SERVER, SOFTWARE, FACILITY, DATA
    status: Mapped[str] = mapped_column(String, default="ACTIVE")
    
    value: Mapped[Optional[float]] = mapped_column(Float)
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class Vendor(Base):
    """Third-party suppliers and partners."""
    __tablename__ = "eg_vendors"
    
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    
    name: Mapped[str] = mapped_column(String)
    service_provided: Mapped[Optional[str]] = mapped_column(String)
    
    risk_score: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String, default="ACTIVE")
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class Customer(Base):
    """Clients or Customers."""
    __tablename__ = "eg_customers"
    
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    
    name: Mapped[str] = mapped_column(String)
    segment: Mapped[Optional[str]] = mapped_column(String)
    
    arr: Mapped[Optional[float]] = mapped_column(Float) # Annual Recurring Revenue
    health_score: Mapped[float] = mapped_column(Float, default=1.0)
    
    status: Mapped[str] = mapped_column(String, default="ACTIVE") # ACTIVE, CHURNED
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class Policy(Base):
    """Enterprise Policies governing rules."""
    __tablename__ = "eg_policies"
    
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    
    title: Mapped[str] = mapped_column(String)
    description: Mapped[str] = mapped_column(Text)
    domain: Mapped[str] = mapped_column(String) # HR, IT, FINANCE
    
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
