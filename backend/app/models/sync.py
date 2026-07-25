"""KAEOS - bidirectional sync ledger + outbound write-back queue.

Two truths this layer maintains:

* SyncLedger - the audit spine of the sync engine. EVERY record that crosses
  the boundary (inbound webhook/poll, outbound write-back) leaves a row here,
  applied or not. A governance product cannot move data silently.

* OutboundWrite - the durable write-back queue. When a governed action mutates
  KAEOS state (actuation, mission step, workflow transition), the change is
  queued here and a dispatcher pushes it to the connected external system
  through the provider adapter. Durable-by-design: a crash between the
  internal commit and the external call leaves a PENDING row the dispatcher
  retries, never a silently-lost update.
"""
from sqlalchemy import Column, String, DateTime, JSON, Text, Integer
from sqlalchemy.sql import func
import uuid

from app.models.domain import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class SyncLedger(Base):
    __tablename__ = "sync_ledger"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    connector_id = Column(String, nullable=True, index=True)
    provider = Column(String(64), nullable=False)

    direction = Column(String(8), nullable=False)     # IN | OUT
    entity_type = Column(String(64), nullable=False)  # employee, account, opportunity, ticket, incident, ...
    external_id = Column(String(256), nullable=True)
    internal_id = Column(String, nullable=True)
    op = Column(String(16), nullable=False)           # UPSERT | DELETE
    status = Column(String(24), nullable=False)       # APPLIED | FAILED | SKIPPED
    detail = Column(Text, nullable=True)              # error text or skip reason

    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)


class OutboundWrite(Base):
    __tablename__ = "outbound_writes"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)

    provider = Column(String(64), nullable=True)      # target provider; NULL = route by category
    category = Column(String(64), nullable=True)      # connector category to route to (hris, crm, ...)
    entity_type = Column(String(64), nullable=False)
    internal_id = Column(String, nullable=False)
    external_id = Column(String(256), nullable=True)
    op = Column(String(16), nullable=False)           # UPSERT | DELETE
    payload = Column(JSON, nullable=False, default=dict)

    status = Column(String(24), nullable=False, default="PENDING", index=True)
    # PENDING -> SENT | FAILED | SKIPPED_NO_CONNECTOR | SKIPPED_NO_CREDENTIALS
    attempts = Column(Integer, nullable=False, default=0)
    last_error = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
