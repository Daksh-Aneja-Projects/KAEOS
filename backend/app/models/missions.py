"""Cross-Domain Autonomous Missions (v3 Phase 3).

Autonomy that PURSUES goals: a plain-language objective is decomposed into a DAG
of real skills spanning departments, each still passing the 7 gates, with a
budget gate, HITL checkpoints, and a shared mission ledger. A mission is the
goal-level orchestration layer above per-skill execution and per-domain workflow.
"""
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional
import uuid

from sqlalchemy import String, DateTime, JSON, Integer, Float, Numeric, Text, Boolean, Index, text
from sqlalchemy.orm import Mapped, mapped_column

# Mission money is exact decimal, not binary float: spent_usd accumulates per-step
# LLM costs and the budget gate compares against a hard cap, so float drift could
# fire a step early or let one extra paid step slip past the cap. Scale 6 matches
# cost_events.cost_usd Numeric(12,6) so sub-cent per-call costs are not truncated.
_MONEY = Numeric(18, 6)

from app.core.database import Base


# ── Mission status lifecycle ─────────────────────────────────────────────
#   PLANNING  -> RUNNING -> (AWAITING_HITL <-> RUNNING) -> COMPLETED
#                        \-> BUDGET_BLOCKED -> (RUNNING | ABORTED)
#                        \-> FAILED | ABORTED
MISSION_STATES = {"PLANNING", "RUNNING", "AWAITING_HITL", "BUDGET_BLOCKED",
                  "COMPLETED", "FAILED", "ABORTED"}
STEP_STATES = {"PENDING", "READY", "RUNNING", "AWAITING_HITL", "DONE", "FAILED", "SKIPPED"}


class Mission(Base):
    __tablename__ = "missions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    goal: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="PLANNING", index=True)

    budget_usd: Mapped[Optional[Decimal]] = mapped_column(_MONEY, nullable=True)   # None = uncapped
    # server_default matches the migration DDL: a raw INSERT that omits this
    # column gets 0, not NULL, so the budget gate never sums a NULL spend.
    spent_usd: Mapped[Decimal] = mapped_column(_MONEY, default=Decimal("0"), server_default=text("0"))

    narrative: Mapped[Optional[str]] = mapped_column(Text, nullable=True)        # why this plan
    departments: Mapped[list] = mapped_column(JSON, default=list)                # departments in scope
    created_by: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class MissionStep(Base):
    __tablename__ = "mission_steps"
    __table_args__ = (Index("ix_mission_steps_mission_seq", "mission_id", "seq"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    mission_id: Mapped[str] = mapped_column(String, nullable=False, index=True)

    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    department: Mapped[str] = mapped_column(String(64), nullable=False)
    skill_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)       # real skill it maps to
    confidence: Mapped[float] = mapped_column(Float, default=0.0)

    depends_on: Mapped[list] = mapped_column(JSON, default=list)                 # list of prerequisite seqs
    hitl_required: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(24), default="PENDING")

    # The persisted approval record for this step's HITL checkpoint. Set ONLY by
    # resolve_hitl_step on human approval; the executor derives its pre-approval
    # flags from these columns, never from hitl_required (a requirement is not
    # evidence an approval happened).
    approved_by: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Optional governed write-back intent {system, object_type, external_id,
    # operation, payload}. When present on a HUMAN-APPROVED (hitl_required) step,
    # the runtime's Gate 5b performs the idempotent, reversible actuation AFTER the
    # compliance/fairness/HITL/debate gates pass — this is what turns a mission
    # from "recommend" into governed "do" (closes the L7 loop).
    actuation: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    execution_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    result_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # server_default matches the migration DDL (see spent_usd above).
    cost_usd: Mapped[Decimal] = mapped_column(_MONEY, default=Decimal("0"), server_default=text("0"))

    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class MissionEvent(Base):
    """The mission ledger: an append-only narrative of what the mission did."""
    __tablename__ = "mission_events"
    __table_args__ = (Index("ix_mission_events_mission_created", "mission_id", "created_at"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    mission_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    step_seq: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    kind: Mapped[str] = mapped_column(String(32), nullable=False)   # PLANNED|STARTED|STEP_DONE|HITL_PAUSE|BUDGET_BLOCK|COMPLETED|ABORTED|STEP_FAILED
    message: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
