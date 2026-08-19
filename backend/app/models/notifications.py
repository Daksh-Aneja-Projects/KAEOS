"""KAEOS - outbound notification channels + delivery ledger.

A NotificationChannel is a tenant-configured delivery target (SMTP mailbox,
Slack incoming webhook, or a generic webhook URL) subscribed to a set of
platform events (hitl.pending, mission.checkpoint, sla.breach,
security.incident, user.invited, digest.weekly). Secrets inside the channel
config are Fernet-encrypted at rest (same KDF as connector credentials).

Every attempt is recorded in NotificationDelivery so operators can audit what
was sent where - governance products cannot have silent side channels.
"""
from sqlalchemy import Column, String, Boolean, DateTime, JSON, Text
from sqlalchemy.sql import func

from app.models.domain import Base
from app.models.mixins import new_uuid as _uuid




# Events a channel can subscribe to. Kept as a module constant so routes and
# the notifier validate against one vocabulary.
NOTIFY_EVENTS = (
    "hitl.pending",         # a governed execution paused for a human
    "mission.checkpoint",   # a mission reached an approval checkpoint
    "sla.breach",           # an automation escalation fired
    "security.incident",    # a security event was ingested / playbook ran
    "user.invited",         # a magic-link invite was issued
    "digest.weekly",        # the scheduled executive digest
)

CHANNEL_KINDS = ("smtp", "slack", "webhook")


class NotificationChannel(Base):
    __tablename__ = "notification_channels"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)

    name = Column(String(128), nullable=False)
    kind = Column(String(16), nullable=False)            # smtp | slack | webhook
    # Fernet-encrypted JSON. smtp: host, port, username, password, use_tls,
    # from_addr, to_addrs[]. slack: webhook_url. webhook: url, secret (optional
    # HMAC signing secret).
    config_encrypted = Column(Text, nullable=False)
    # Subscribed events; empty list = all events.
    events = Column(JSON, nullable=False, default=list)
    enabled = Column(Boolean, nullable=False, default=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class NotificationDelivery(Base):
    __tablename__ = "notification_deliveries"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    channel_id = Column(String, nullable=False, index=True)

    event = Column(String(64), nullable=False)
    subject = Column(String(256), nullable=False)
    status = Column(String(16), nullable=False)          # SENT | FAILED
    error = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
