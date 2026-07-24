"""System-of-Record actuation models (v3 Phase 1).

Autonomy that DOES: a governed, idempotent, reversible write-back path to a
system of record. Every outbound mutation is recorded as an ActionRecord (the
Actions Ledger, distinct from the provenance *decision* ledger) carrying an
idempotency key, a provenance id, the before/after state, and a compensator so
it can be reversed. The backing state lives in SorObject — a real, per-tenant
sandbox system-of-record we actuate against and reconcile the twin with.
"""
from datetime import datetime, timezone
from typing import Optional
import uuid

from sqlalchemy import String, DateTime, JSON, Integer, Text, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class SorObject(Base):
    """A record in a (sandbox) system of record — the real state KAEOS actuates.

    Uniqueness is (tenant, system, object_type, external_id): one canonical row
    per external object. `version` bumps on every governed write so drift (a
    change made outside the actuation path) is detectable.
    """
    __tablename__ = "sor_objects"
    __table_args__ = (
        UniqueConstraint("tenant_id", "system", "object_type", "external_id",
                         name="uq_sor_object_identity"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    system: Mapped[str] = mapped_column(String(64), nullable=False)          # netsuite | workday | salesforce | ...
    object_type: Mapped[str] = mapped_column(String(64), nullable=False)     # invoice | employee | opportunity | ...
    external_id: Mapped[str] = mapped_column(String(128), nullable=False)
    state: Mapped[dict] = mapped_column(JSON, default=dict)                   # current field values
    version: Mapped[int] = mapped_column(Integer, default=0)
    deleted: Mapped[bool] = mapped_column(Integer, default=0)                 # soft-delete (reversible)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class ActionRecord(Base):
    """One governed write KAEOS performed against a system of record.

    Distinct from the provenance *decision* ledger: this is the *actuation*
    ledger — what KAEOS actually DID to a real system, and how to undo it.
    """
    __tablename__ = "action_records"
    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_action_idempotency"),
        Index("ix_action_records_tenant_created", "tenant_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    execution_id: Mapped[Optional[str]] = mapped_column(String, index=True, nullable=True)

    system: Mapped[str] = mapped_column(String(64), nullable=False)
    object_type: Mapped[str] = mapped_column(String(64), nullable=False)
    external_id: Mapped[str] = mapped_column(String(128), nullable=False)
    operation: Mapped[str] = mapped_column(String(16), nullable=False)       # CREATE | UPDATE | DELETE

    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    before_state: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    after_state: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    compensator: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)  # how to reverse this action

    status: Mapped[str] = mapped_column(String(16), default="APPLIED")       # APPLIED | FAILED | REVERSED
    provenance_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    actor: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    reversed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
