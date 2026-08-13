"""
KAEOS Operations Domain — Core Models
Operations team members and configs.
"""
from sqlalchemy import Column, String, Integer, DateTime, Boolean, Float, UniqueConstraint
from sqlalchemy.sql import func
import uuid

from app.models.domain import Base

def _uuid():
    return str(uuid.uuid4())

class OpsTeamMember(Base):
    """Roster of internal operations coordinators, project managers, and facilities handlers."""
    __tablename__ = "ops_team_members"
    # Tenant-scoped business key: global unique caused cross-tenant collisions.
    __table_args__ = (
        UniqueConstraint("tenant_id", "email", name="uq_ops_team_tenant_email"),
    )

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)

    name = Column(String(128), nullable=False)
    role = Column(String(64), nullable=False)  # Program Manager, Facilities Manager, QA Engineer
    email = Column(String(128), nullable=False)
    is_active = Column(Boolean, default=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

class DepartmentConfig(Base):
    """Global configuration settings for department operations (e.g. signature limits)."""
    __tablename__ = "ops_department_configs"
    # Tenant-scoped business key: global unique caused cross-tenant collisions.
    __table_args__ = (
        UniqueConstraint("tenant_id", "department_slug", name="uq_ops_dept_tenant_slug"),
    )

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)

    department_slug = Column(String(64), nullable=False)  # hr, finance, support
    auto_approval_limit = Column(Float, default=1000.00)
    audit_frequency_days = Column(Integer, default=90)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
