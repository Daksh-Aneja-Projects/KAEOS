"""Company Brain — self-proposed, human-governed missions.

The reactive loop turns an EXTERNAL signal into a mission. The Brain closes the
loop from the other end: it reflects on the operational reality KAEOS already
records (declining safe-autonomy rate, cost spikes, systems-of-record drift,
recurring mission failures, a knowledge backlog) and PROPOSES its own missions.

A proposal carries no authority. It is inert until a human approves it, and even
then the mission it spawns runs every step through the same 7 gates. This is the
governance boundary that keeps a self-directing brain safe: the brain proposes,
a human disposes, the gates execute. The ``outcome`` column is stamped from the
spawned mission's terminal status, closing the meta-loop so the brain can learn
which KINDS of proposal are worth making.
"""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import String, DateTime, JSON, Float, Text, Index
from sqlalchemy.orm import Mapped, mapped_column

# Base from app.models.domain (not app.core.database) matches the sibling models
# imported in app/models/__init__.py — importing it from core here would form a
# circular import when the models package initialises.
from app.models.domain import Base
from app.models.mixins import new_uuid as _uuid

# PENDING -> APPROVED (mission_id set) -> outcome SUCCEEDED|FAILED
#         \-> REJECTED (feeds the cooldown that suppresses re-proposing the kind)
#         \-> SUPERSEDED (a fresher proposal for the same subject replaced it)
PROPOSAL_STATES = {"PENDING", "APPROVED", "REJECTED", "SUPERSEDED"}
PROPOSAL_OUTCOMES = {"SUCCEEDED", "FAILED"}


class BrainProposal(Base):
    """One mission the Company Brain proposed from observed operational reality."""

    __tablename__ = "brain_proposals"
    __table_args__ = (
        # The dedup / cooldown read: WHERE tenant_id=? AND dedup_key=? ORDER BY created_at.
        Index("ix_brain_proposals_dedup", "tenant_id", "dedup_key", "created_at"),
        Index("ix_brain_proposals_status", "tenant_id", "status"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    goal: Mapped[str] = mapped_column(Text, nullable=False)       # fed verbatim to plan_mission on approval
    rationale: Mapped[str] = mapped_column(Text, nullable=False)  # why the brain proposed it, plain English
    evidence: Mapped[list] = mapped_column(JSON, default=list)    # [{kind, ref, detail}] grounding rows

    signal_kind: Mapped[str] = mapped_column(String(32), nullable=False)   # dominant trigger
    # Stable per (kind, subject) so one open proposal exists per condition and a
    # recently-rejected one is suppressed for a cooldown — the brain's memory of
    # what the human already said no to.
    dedup_key: Mapped[str] = mapped_column(String(160), nullable=False)
    priority: Mapped[float] = mapped_column(Float, default=0.0)   # 0..1 materiality, meta-learning weighted

    # No column-level index: the composite ix_brain_proposals_status(tenant_id,
    # status) below already serves status-filtered reads (and a per-column index
    # of the same name would collide with it under create_all). NOT NULL +
    # server_default mirrors migration 0057 so the drift gate sees one shape.
    status: Mapped[str] = mapped_column(
        String(16), default="PENDING", server_default="PENDING", nullable=False)
    mission_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)   # set on approval
    outcome: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)  # from the mission's terminal status

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by: Mapped[Optional[str]] = mapped_column(String, nullable=True)
