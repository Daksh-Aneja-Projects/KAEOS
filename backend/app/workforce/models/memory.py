"""
KAEOS Workforce Layer — Enterprise Memory Models

This is the organizational learning engine. Every decision made by an agent
(or a human overriding an agent) is logged here. Over time, this forms a
knowledge graph of "how this company makes decisions," allowing the agents
to learn and adapt to company culture without explicit rules.
"""
from sqlalchemy import (
    Column, String, Integer, Float, DateTime, Text, JSON,
    Enum, ForeignKey, Index,
)
from sqlalchemy.sql import func
import uuid
import enum

from app.models.domain import Base


def _uuid():
    return str(uuid.uuid4())


class MemoryType(str, enum.Enum):
    DECISION = "DECISION"                     # Standard operational decision
    EXCEPTION = "EXCEPTION"                   # Edge case or error handling
    APPROVAL = "APPROVAL"                     # Human approval given
    REJECTION = "REJECTION"                   # Human approval denied
    POLICY_INTERPRETATION = "POLICY_INTERP"   # Interpreted a vague policy
    OUTCOME = "OUTCOME"                       # Result of a past decision
    LESSON_LEARNED = "LESSON_LEARNED"         # Synthesized learning from outcomes


class EnterpriseMemory(Base):
    """
    Organizational memory — the collective experience of the workforce.

    Stores synthesized learnings, interpreted rules, and outcomes.
    Unlike raw decision logs, this is the "distilled" knowledge that agents
    query before acting in ambiguous situations.
    """
    __tablename__ = "enterprise_memory"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    department_id = Column(String, ForeignKey("departments.id"), nullable=True, index=True)

    # Content
    memory_type = Column(Enum(MemoryType), default=MemoryType.DECISION, index=True)
    content = Column(Text, nullable=False)                   # "When policy X is ambiguous, we generally favor Y"
    context = Column(JSON, default=dict)                     # The situation surrounding this memory

    # Source references (how we know this)
    source_process_id = Column(String, ForeignKey("business_processes.id"), nullable=True)
    source_agent_id = Column(String, ForeignKey("department_agents.id"), nullable=True)
    source_case_id = Column(String, nullable=True)           # E.g., an HR case ID

    # Quality metrics
    confidence = Column(Float, default=1.0)                  # How sure are we this is still valid
    was_correct = Column(String(8), nullable=True)           # "true" or "false" (filled in when outcome is known)
    usage_count = Column(Integer, default=0)                 # How many times this memory has been recalled

    # Classification
    tags = Column(JSON, default=list)                        # Searchable tags
    embedding_id = Column(String, nullable=True)             # Reference to vector DB entry (if external)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_enterprise_memory_search", "tenant_id", "department_id", "memory_type"),
    )


class DecisionLog(Base):
    """
    Immutable ledger of every significant decision made by the system.

    Provides total transparency into WHY an agent took an action. Includes
    the full reasoning chain, evidence cited, and confidence score. Crucial
    for audits, compliance, and debugging.
    """
    __tablename__ = "decision_logs"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    department_id = Column(String, ForeignKey("departments.id"), nullable=False, index=True)

    # Actor
    agent_id = Column(String, ForeignKey("department_agents.id"), nullable=True, index=True)
    process_execution_id = Column(String, ForeignKey("process_executions.id"), nullable=True)

    # Decision details
    decision_type = Column(String(64), nullable=False)       # "screen_candidate", "approve_expense"
    question = Column(Text, nullable=False)                  # What was asked
    answer = Column(Text, nullable=False)                    # What was decided

    # The "Why"
    reasoning_chain = Column(JSON, default=list)             # Step-by-step logic
    # Schema: [{"step": 1, "thought": "...", "conclusion": "..."}]

    evidence_ids = Column(JSON, default=list)                # References to policies or data used
    confidence = Column(Float, default=1.0)                  # AI confidence in this specific decision
    compliance_tags = Column(JSON, default=list)             # Any compliance frameworks involved

    # Human oversight
    was_overridden = Column(String(8), default="false")      # Did a human change this later?
    override_by = Column(String, nullable=True)              # User ID
    override_reason = Column(Text, nullable=True)            # Why it was changed

    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    __table_args__ = (
        Index("ix_decision_logs_lookup", "tenant_id", "department_id", "decision_type"),
    )
