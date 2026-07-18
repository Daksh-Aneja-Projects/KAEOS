"""
KAEOS — Reality Experience persistence.

The reality feed and shock history previously lived in module-level Python
lists: wiped on every restart, shared across tenants, and invisible to any
other process. That contradicted the platform's own durability and tenancy
guarantees, so they are real tables now.
"""
from sqlalchemy import Column, String, DateTime, Float, JSON, Integer
from sqlalchemy.sql import func
import uuid

from app.models.domain import Base


def _uuid():
    return str(uuid.uuid4())


class RealityEvent(Base):
    """An entry in the reality provenance feed."""
    __tablename__ = "reality_events"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    event = Column(String(512), nullable=False)
    event_metadata = Column(JSON, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)


class ShockOutcome(Base):
    """A recorded shock simulation and the decision taken — feeds the learning loop."""
    __tablename__ = "reality_shock_outcomes"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)

    shock_type = Column(String(64), nullable=False)
    target = Column(String(256), nullable=True)
    severity = Column(Float, nullable=True)
    decision = Column(String(256), nullable=True)
    options_evaluated = Column(Integer, default=0)
    impact = Column(JSON, default=dict)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
