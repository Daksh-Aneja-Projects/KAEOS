"""
KAEOS S1 — System Events Model

Stores platform-wide events emitted by the Event Bus.
"""
from sqlalchemy import (
    Column, String, Boolean, Integer, DateTime, JSON,
)
from sqlalchemy.sql import func
import uuid

from app.models.domain import Base

def _uuid():
    return str(uuid.uuid4())

class SystemEvent(Base):
    """Immutable log of system-wide events."""
    __tablename__ = 'system_events'

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    event_type = Column(String(64), nullable=False, index=True)
    payload = Column(JSON, default=dict)
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), index=True)

class WebhookSubscriptionModel(Base):
    """Database representation of a webhook subscription."""
    __tablename__ = 'webhook_subscriptions'

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    name = Column(String(128), nullable=False)
    endpoint = Column(String(512), nullable=False)
    events = Column(JSON, nullable=False)  # List of event types
    secret = Column(String(128), nullable=False)
    active = Column(Boolean, default=True)
    delivery_count = Column(Integer, default=0)
    failure_count = Column(Integer, default=0)
    last_delivered_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
