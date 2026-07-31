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
from sqlalchemy import Column, String, Text, JSON, Float, Boolean, DateTime, Integer
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


class ModelEvolutionRun(Base):
    """Phase 3 — one governed model-evolution evaluation + promotion decision.

    "Model evolution" here is HONEST about what it does: it takes a candidate
    model (a stronger model, or one fine-tuned externally on this tenant's Phase-2
    export) and MEASURES it against the tenant's current baseline model on a
    held-out slice of the tenant's own governed training examples, producing real
    win/loss scores. A candidate is only ever PROMOTED (made the tenant's model
    for a tier) if it genuinely beats the baseline AND a human approves — the same
    gated-deploy discipline the rest of the platform uses.

    Deliberately NOT claimed: this table does not itself fine-tune weights. The
    actual training step is external/pluggable; what ships here is the real
    evaluation-and-gated-promotion loop. When evaluation runs without a live LLM
    provider, ``simulated`` is set and the run can never win or be promoted — a
    fabricated score must never drive a model swap.
    """
    __tablename__ = "model_evolution_runs"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)

    tier = Column(String(24), nullable=False)               # reasoning | classification | fast
    baseline_model = Column(String(128), nullable=False)
    candidate_model = Column(String(128), nullable=False)

    # PENDING → EVALUATING → EVALUATED → PENDING_REVIEW → (PROMOTED | REJECTED); FAILED on error
    status = Column(String(24), default="PENDING", index=True)

    eval_size = Column(Integer, default=0)                   # examples actually scored
    baseline_score = Column(Float, nullable=True)           # mean 0..1 over the eval set
    candidate_score = Column(Float, nullable=True)
    score_delta = Column(Float, nullable=True)              # candidate - baseline
    win = Column(Boolean, default=False)                    # candidate beat baseline by the margin
    simulated = Column(Boolean, default=False)              # eval ran without a real provider → not trustworthy

    detail = Column(JSON, default=dict)                     # {margin, metric, per_example:[...], notes}
    # sha256 of the concatenated held-out eval prompts — reproducibility: the same
    # deterministic eval slice always hashes the same, so two runs are comparable
    # and a scoring change is attributable to the model, not a shifted prompt set.
    prompt_hash = Column(String(64), nullable=True)
    decision = Column(String(24), nullable=True)           # PROMOTED | REJECTED
    decided_by = Column(String(128), nullable=True)
    decided_at = Column(DateTime(timezone=True), nullable=True)
    error = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class FineTuneJob(Base):
    """Phase 4 — the EXTERNAL fine-tune bridge (closes the L2 loop).

    Model evolution measures + promotes a candidate; this is the missing step
    that PRODUCES the candidate: submit the tenant's curated positive examples to
    an external fine-tuning provider, poll to completion, and on success
    auto-trigger a real evaluation (``ModelEvolutionRun``). Promotion stays
    HUMAN-gated — the bridge only fills the funnel with a measured candidate.

    Tenant-scoped, NOT in GLOBAL_TABLES, so RLS isolates one tenant's jobs.
    """
    __tablename__ = "finetune_jobs"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)

    tier = Column(String(24), nullable=False)                # reasoning | classification | fast
    provider = Column(String(32), nullable=False, default="")  # openai | ...
    base_model = Column(String(128), nullable=False, default="")
    external_job_id = Column(String(128), nullable=True)     # the provider's job handle

    # SUBMITTED → RUNNING → SUCCEEDED → EVALUATING → EVALUATED ; FAILED on error
    status = Column(String(24), default="SUBMITTED", index=True)
    example_count = Column(Integer, default=0)
    result_model = Column(String(128), nullable=True)        # the fine-tuned model id
    eval_run_id = Column(String, nullable=True)              # -> ModelEvolutionRun.id (auto-eval)
    error = Column(Text, nullable=True)
    # Consecutive provider-poll failures. Persisted (not in-process) so a job with
    # a permanently broken handle still dead-letters across worker restarts.
    poll_errors = Column(Integer, default=0, nullable=False, server_default="0")

    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


# Evaluation labels, most-valuable first. Kept here so the builder, routes, and
# tests agree on one vocabulary.
LABEL_CORRECTED = "CORRECTED"   # human edited the answer - the strongest supervised signal
LABEL_APPROVED = "APPROVED"     # a human approved the agent's answer unchanged at a HITL gate
LABEL_GOLD = "GOLD"             # high-confidence clean success, no human needed
LABEL_NEGATIVE = "NEGATIVE"     # blocked/rejected - useful as a contrastive/negative example

POSITIVE_LABELS = (LABEL_CORRECTED, LABEL_APPROVED, LABEL_GOLD)
