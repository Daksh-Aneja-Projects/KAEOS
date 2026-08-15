"""
KAEOS Support Domain — Core Models
Support agents and channel routing.
"""
from sqlalchemy import Column, String, Integer, DateTime, Boolean, Enum, ForeignKey, Numeric, UniqueConstraint
from sqlalchemy.sql import func
import uuid
import enum

from app.models.domain import Base

def _uuid():
    return str(uuid.uuid4())

class ChannelType(str, enum.Enum):
    EMAIL = "EMAIL"
    CHAT = "CHAT"
    PHONE = "PHONE"
    PORTAL = "PORTAL"

class SupportTeam(Base):
    """Teams/Tiers of support (e.g. Tier 1, Technical Escalation, Billing Support)."""
    __tablename__ = "sup_teams"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)

    name = Column(String(128), nullable=False)
    description = Column(String(256), nullable=True)
    tier = Column(Integer, default=1)  # Tier 1, 2, 3

    created_at = Column(DateTime(timezone=True), server_default=func.now())

class SupportAgent(Base):
    """Support agents (both human reps and AI digital twins)."""
    __tablename__ = "sup_agents"
    # Tenant-scoped business key: global unique caused cross-tenant collisions.
    __table_args__ = (
        UniqueConstraint("tenant_id", "email", name="uq_sup_agent_tenant_email"),
    )

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)

    name = Column(String(128), nullable=False)
    email = Column(String(128), nullable=False)
    team_id = Column(String, ForeignKey("sup_teams.id"), nullable=True)
    
    is_ai = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    # Average CSAT rating (1.00-5.00) across surveys tied to tickets this agent
    # resolved. Computed + persisted by GET /support/agents/leaderboard - never
    # hand-set, so it always reflects real CustomerSatisfaction rows.
    avg_csat = Column(Numeric(3, 2), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

class SupportChannel(Base):
    """Ingress channels (e.g. support@company.com, Web Portal widget)."""
    __tablename__ = "sup_channels"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)

    channel_name = Column(String(64), nullable=False)
    channel_type = Column(Enum(ChannelType), default=ChannelType.EMAIL)
    routing_team_id = Column(String, ForeignKey("sup_teams.id"), nullable=True)
    is_active = Column(Boolean, default=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
