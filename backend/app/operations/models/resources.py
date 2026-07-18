"""
KAEOS Operations Domain — Resource Models
"""
from sqlalchemy import Column, String, DateTime, ForeignKey, Integer, Float, Numeric
from sqlalchemy.sql import func
import uuid

from app.models.domain import Base

def _uuid():
    return str(uuid.uuid4())

class Resource(Base):
    """Assets or developers tracked for capacity constraints (e.g. servers, PMs, QA specialists)."""
    __tablename__ = "ops_resources"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)

    name = Column(String(128), nullable=False)
    resource_type = Column(String(64), nullable=False) # DEVELOPER, SERVER, FACILITY
    cost_per_hour = Column(Numeric(12, 2), default=0.00)
    is_available = Column(DateTime(timezone=True), nullable=True) # Used for timestamp or ignored

    created_at = Column(DateTime(timezone=True), server_default=func.now())

class ResourceAllocation(Base):
    """Assignments linking resources to projects for specific hour capacities."""
    __tablename__ = "ops_resource_allocations"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    resource_id = Column(String, ForeignKey("ops_resources.id"), nullable=False, index=True)
    project_id = Column(String, ForeignKey("ops_projects.id"), nullable=False, index=True)

    allocated_hours = Column(Float, default=0.00)
    utilization_percentage = Column(Float, default=0.00) # 0 to 100

    created_at = Column(DateTime(timezone=True), server_default=func.now())

class CapacityPlan(Base):
    """Quarterly forecasts for resource requirements based on project demands."""
    __tablename__ = "ops_capacity_plans"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)

    quarter = Column(String(16), nullable=False) # e.g. "Q3-2026"
    headcount_requested = Column(Integer, default=0)
    estimated_budget = Column(Numeric(18, 2), default=0.00)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
