"""
KAEOS v2 — Enterprise AI Foundry, Phase 2: Learning Intelligence.

The v1 platform already logs every governed decision as a SkillExecution row:
the instruction (task_intent), the grounding context, the reasoning chain, the
outcome, and whether a human approved it. That is, structurally, a training
example that has already walked the 7-gate pipeline.

This module curates those rows into an explicit, exportable training dataset -
the first step of turning "learning by memory" into "learning by model". Because
every example is derived from a governed execution, the dataset inherits the
platform's guarantees: nothing blocked at the compliance gate, and nothing a
human rejected, is ever presented as something to learn from.

The table carries tenant_id and is NOT in GLOBAL_TABLES, so the RLS startup
sweep in app/core/database.py puts it under the same tenant_isolation policy as
every other tenant table - one enterprise's training data is never visible to
another's.
"""
from sqlalchemy import Column, String, Text, JSON, Float, Boolean, DateTime
from sqlalchemy.sql import func
import uuid

from app.models.domain import Base


def _uuid():
    return str(uuid.uuid4())


class TrainingExample(Base):
    """One curated {instruction, context, ideal_answer, reasoning, evaluation} tuple.

    Mined from a real SkillExecution, or written directly from a human
    correction/rating. `source_execution_id` is a correlation id (indexed, no
    FK) exactly like provenance_ledger.rule_id: an execution may yield both a
    mined row and a later human-corrected row, and executions can be pruned
    without orphaning the dataset.
    """
    __tablename__ = "training_examples"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    domain = Column(String(32), index=True)                 # hr / finance / legal / sales / support / operations / engineering

    # The training tuple
    instruction = Column(Text, nullable=False)              # what the agent was asked to do
    context = Column(JSON, default=dict)                    # the grounding facts it reasoned over
    ideal_answer = Column(Text, nullable=True)              # the accepted answer (human-corrected when edited)
    reasoning = Column(JSON, default=list)                  # the reasoning chain that produced it

    # Curation
    evaluation_label = Column(String(24), index=True)       # GOLD | APPROVED | CORRECTED | NEGATIVE
    quality_score = Column(Float, default=0.0)              # 0-1, higher = better training signal
    human_verified = Column(Boolean, default=False)         # a human explicitly approved/corrected/rated this

    # Provenance
    source = Column(String(24), default="mined")            # mined | human_correction | human_rating
    source_execution_id = Column(String, index=True, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)


# Evaluation labels, most-valuable first. Kept here so the builder, routes, and
# tests agree on one vocabulary.
LABEL_CORRECTED = "CORRECTED"   # human edited the answer - the strongest supervised signal
LABEL_APPROVED = "APPROVED"     # a human approved the agent's answer unchanged at a HITL gate
LABEL_GOLD = "GOLD"             # high-confidence clean success, no human needed
LABEL_NEGATIVE = "NEGATIVE"     # blocked/rejected - useful as a contrastive/negative example

POSITIVE_LABELS = (LABEL_CORRECTED, LABEL_APPROVED, LABEL_GOLD)
