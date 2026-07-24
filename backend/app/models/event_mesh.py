"""Sense-Decide-Act Event Mesh (v3 Phase 5).

External-world signals (regulatory feeds, vendor/status alerts, market moves,
security advisories, news) ingested, correlated against the Enterprise Twin, and
turned into a governed response (a briefing, a HITL, or none). This is KAEOS's
enterprise OODA loop: sense the outside, decide against the twin, act under
governance.
"""
from datetime import datetime, timezone
from typing import Optional
import uuid

from sqlalchemy import String, DateTime, JSON, Float, Text, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

SIGNAL_KINDS = {"REGULATORY", "VENDOR", "MARKET", "SECURITY", "NEWS", "SUPPLY_CHAIN"}
RESPONSE_KINDS = {"NONE", "BRIEFING", "HITL", "MISSION"}


class ExternalSignal(Base):
    __tablename__ = "external_signals"
    __table_args__ = (Index("ix_external_signals_tenant_created", "tenant_id", "created_at"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)          # REGULATORY | VENDOR | ...
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    body: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    severity: Mapped[str] = mapped_column(String(16), default="info")       # info | warning | critical
    authority_score: Mapped[float] = mapped_column(Float, default=0.5)
    novelty_score: Mapped[float] = mapped_column(Float, default=0.5)

    matched_entities: Mapped[list] = mapped_column(JSON, default=list)      # twin entities the signal touches
    correlation_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    response_kind: Mapped[str] = mapped_column(String(16), default="NONE")
    response_ref: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # mission id / activity id
    status: Mapped[str] = mapped_column(String(16), default="NEW")          # NEW | CORRELATED | RESPONDED

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    responded_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
