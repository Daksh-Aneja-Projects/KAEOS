"""
KAEOS — User & RBAC Models
Roles: ADMIN (full access), ANALYST (read + execute), VIEWER (read only)
"""
from sqlalchemy import Column, String, Boolean, Integer, DateTime, Enum
from sqlalchemy.sql import func
import uuid
import enum

from app.models.domain import Base


def _uuid():
    return str(uuid.uuid4())


class UserRole(str, enum.Enum):
    ADMIN = "ADMIN"         # Full access: CRUD users, all modules, config
    ANALYST = "ANALYST"     # Read + Execute: run agents, view dashboards, no user mgmt
    VIEWER = "VIEWER"       # Read only: dashboards, reports, no execution


class User(Base):
    """Platform user with RBAC role assignment."""
    __tablename__ = 'users'

    id = Column(String, primary_key=True, default=_uuid)
    email = Column(String, unique=True, nullable=False, index=True)
    display_name = Column(String, nullable=False)
    hashed_password = Column(String, nullable=False)
    role = Column(Enum(UserRole), default=UserRole.VIEWER, nullable=False)
    tenant_id = Column(String, default="default", nullable=False, index=True)

    is_active = Column(Boolean, default=True)
    is_demo = Column(Boolean, default=False)

    # Tracking
    login_count = Column(Integer, default=0)
    last_login_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    created_by = Column(String, nullable=True)  # ID of user who created this account
