"""KAEOS - bidirectional sync ledger + outbound write-back queue.

Two truths this layer maintains:

* SyncLedger - the audit spine of the sync engine. EVERY record that crosses
  the boundary (inbound webhook/poll, outbound write-back) leaves a row here,
  applied or not. A governance product cannot move data silently.

* OutboundWrite - the durable write-back queue. When the actuation path
  executes a governed action (the ONLY producer today - mission steps and
  workflow transitions do not queue write-backs), the change is queued here
  and a dispatcher pushes it to the connected external system through the
  provider adapter. Durable-by-design: a crash between the internal commit
  and the external call leaves a PENDING row the dispatcher retries, never a
  silently-lost update.
"""
from sqlalchemy import Column, String, DateTime, JSON, Text, Integer, UniqueConstraint
from sqlalchemy.sql import func

from app.models.domain import Base
from app.models.mixins import new_uuid as _uuid




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
    # A given (tenant, idempotency_key) must queue AT MOST ONE write: a duplicate
    # queue (retry of the same governed action) must not double-send/double-meter.
    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_outbound_idempotency"),
    )

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
    # PENDING -> SENT | FAILED (retryable) | DEAD (terminal, retries exhausted)
    #         -> SKIPPED_NO_CONNECTOR | SKIPPED_NO_CREDENTIALS
    # DEAD is the dead-letter state: attempts hit MAX and the row is no longer
    # selected for dispatch, but stays queryable/alertable (WHERE status='DEAD')
    # instead of masquerading as a retryable FAILED forever.
    attempts = Column(Integer, nullable=False, default=0)
    last_error = Column(Text, nullable=True)

    # EXTERNAL idempotency token, stable across retries. Sent to the system of
    # record so a create whose HTTP response was lost (read timeout) is deduped
    # on the SoR side rather than creating a second record on the retry. When an
    # actuation queues the write it passes its ActionRecord.idempotency_key so
    # the token ties back to the governed decision.
    idempotency_key = Column(String(64), nullable=False, default=_uuid, index=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
