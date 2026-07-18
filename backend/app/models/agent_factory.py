"""KAEOS — Agent Factory Models (AEOS Integration)
AgentBlueprint, DeployedAgent, DebateTranscript, ActivityFeedEvent
"""
from sqlalchemy import (
    Column, String, Boolean, Integer, Float, DateTime, ForeignKey,
    Text, JSON, Enum,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid
import enum

from app.models.domain import Base


def _uuid():
    return str(uuid.uuid4())


# ─── Enums ───

class BlueprintStatus(str, enum.Enum):
    DRAFTING = "DRAFTING"
    BLUEPRINT_READY = "BLUEPRINT_READY"
    APPROVED = "APPROVED"
    COMPILED = "COMPILED"
    DEPLOYED = "DEPLOYED"
    ARCHIVED = "ARCHIVED"


class AgentType(str, enum.Enum):
    PERSISTENT = "PERSISTENT"
    EPHEMERAL = "EPHEMERAL"
    SCHEDULED = "SCHEDULED"


class AgentStatus(str, enum.Enum):
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    STOPPED = "STOPPED"
    ERROR = "ERROR"
    COMPLETED = "COMPLETED"


class DebateDecision(str, enum.Enum):
    PROCEED = "PROCEED"
    ESCALATE = "ESCALATE"
    BLOCK = "BLOCK"


class ActivityEventType(str, enum.Enum):
    AGENT_STARTED = "AGENT_STARTED"
    AGENT_COMPLETED = "AGENT_COMPLETED"
    AGENT_FAILED = "AGENT_FAILED"
    AGENT_STOPPED = "AGENT_STOPPED"
    AGENT_PAUSED = "AGENT_PAUSED"
    HITL_REQUIRED = "HITL_REQUIRED"
    HITL_APPROVED = "HITL_APPROVED"
    HITL_REJECTED = "HITL_REJECTED"
    DECAY_ALERT = "DECAY_ALERT"
    CONFLICT_DETECTED = "CONFLICT_DETECTED"
    BLUEPRINT_CREATED = "BLUEPRINT_CREATED"
    BLUEPRINT_APPROVED = "BLUEPRINT_APPROVED"
    SKILL_COMPILED = "SKILL_COMPILED"
    EXTRACTION_DISCOVERED = "EXTRACTION_DISCOVERED"
    DEBATE_ESCALATED = "DEBATE_ESCALATED"
    DEBATE_BLOCKED = "DEBATE_BLOCKED"
    FAIRNESS_BLOCKED = "FAIRNESS_BLOCKED"
    FAIRNESS_OVERRIDE = "FAIRNESS_OVERRIDE"
    TEMPORAL_ANOMALY = "TEMPORAL_ANOMALY"
    EXTERNAL_SIGNAL = "EXTERNAL_SIGNAL"
    PROACTIVE_ALERT = "PROACTIVE_ALERT"


class ActivitySeverity(str, enum.Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    ACTION_REQUIRED = "ACTION_REQUIRED"
    CRITICAL = "CRITICAL"


# ─── Blueprint Node/Edge Types ───

class BlueprintNodeType(str, enum.Enum):
    DATA_SOURCE = "DATA_SOURCE"
    TRANSFORM = "TRANSFORM"
    DECISION_GATE = "DECISION_GATE"
    ACTION = "ACTION"
    OUTPUT = "OUTPUT"
    HITL_CHECKPOINT = "HITL_CHECKPOINT"
    FAIRNESS_GATE = "FAIRNESS_GATE"


class BlueprintEdgeType(str, enum.Enum):
    DATA_FLOW = "DATA_FLOW"
    CONDITIONAL_TRUE = "CONDITIONAL_TRUE"
    CONDITIONAL_FALSE = "CONDITIONAL_FALSE"
    ESCALATION = "ESCALATION"


# ─── Models ───

class AgentBlueprint(Base):
    """AEOS Agent Factory — Blueprint persisted from natural language prompt."""
    __tablename__ = 'agent_blueprints'

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)

    # User intent
    name = Column(String, nullable=False)
    description = Column(Text, nullable=False)  # Original NL prompt
    domain = Column(String(64), index=True)
    department = Column(String(64), index=True)

    # Status lifecycle
    status = Column(
        Enum(BlueprintStatus), default=BlueprintStatus.DRAFTING, index=True
    )

    # Blueprint DAG — full graph structure
    # Schema: { nodes: [{id, type, label, config, position}], edges: [{id, source, target, type, label}] }
    blueprint_graph = Column(JSON, default=lambda: {"nodes": [], "edges": []})

    # Brain references — what knowledge this blueprint draws from
    source_skill_ids = Column(JSON, default=list)
    source_rule_ids = Column(JSON, default=list)
    mcp_tools_required = Column(JSON, default=list)

    # Auto-derived guardrails
    guardrails = Column(JSON, default=lambda: {
        "pre_execution": [],
        "post_execution": []
    })
    compliance_tags = Column(JSON, default=list)
    confidence_floor = Column(Float, default=0.0)

    # Intent decomposition (from LLM)
    intent_decomposition = Column(JSON, default=lambda: {
        "intent_class": None,
        "action_type": None,
        "data_sources_needed": [],
        "capabilities_needed": [],
        "temporal_context": None
    })

    # Audit
    created_by = Column(String, nullable=True)
    approved_by = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    approved_at = Column(DateTime(timezone=True), nullable=True)
    deployed_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    deployed_agents = relationship("DeployedAgent", back_populates="blueprint", lazy="selectin")


class DeployedAgent(Base):
    """AEOS Agent Factory — A live running agent compiled from a blueprint."""
    __tablename__ = 'deployed_agents'

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    blueprint_id = Column(String, ForeignKey('agent_blueprints.id'), nullable=False, index=True)

    # Agent identity
    agent_name = Column(String, nullable=False)
    agent_type = Column(Enum(AgentType), default=AgentType.PERSISTENT)
    status = Column(Enum(AgentStatus), default=AgentStatus.RUNNING, index=True)

    # Compiled skill reference
    compiled_skill_id = Column(String, ForeignKey('skills.id'), nullable=True)

    # Trigger configuration
    # Schema: { type: "event"|"schedule"|"manual", config: {...} }
    trigger_config = Column(JSON, default=lambda: {"type": "manual", "config": {}})

    # Runtime stats
    execution_count = Column(Integer, default=0)
    success_count = Column(Integer, default=0)
    last_executed_at = Column(DateTime(timezone=True), nullable=True)

    # Health telemetry
    health_status = Column(JSON, default=lambda: {
        "uptime_pct": 100.0,
        "avg_latency_ms": 0,
        "error_rate": 0.0,
        "last_error": None
    })

    # Lifecycle
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    paused_at = Column(DateTime(timezone=True), nullable=True)
    stopped_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    blueprint = relationship("AgentBlueprint", back_populates="deployed_agents")
    skill = relationship("Skill", foreign_keys=[compiled_skill_id])


class DebateTranscript(Base):
    """AEOS Agent Debate Engine — Proposer/Advocate/Arbitrator transcript.
    
    Persists the full adversarial reasoning exchange for every Tier-1 action.
    Provides the trust mechanism for enterprise production write access.
    """
    __tablename__ = 'debate_transcripts'

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    # Correlation id, NOT a foreign key: the debate gate (Gate 4) writes its
    # transcript BEFORE any SkillExecution exists, and blocked/escalated
    # actions never create one. Postgres enforces FKs (SQLite masked this).
    execution_id = Column(String, nullable=False, index=True)
    skill_id = Column(String, index=True)

    # Tier classification
    tier_level = Column(Integer, default=1)  # 1 = highest stakes
    trigger_reason = Column(String(64))  # compliance_tag, low_confidence, first_execution

    # Proposer phase
    proposer_argument = Column(JSON, default=lambda: {
        "evidence": [],
        "conclusion": "",
        "confidence": 0.0,
        "grounded_in": []  # Rule/skill IDs cited
    })

    # Devil's Advocate phase
    advocate_argument = Column(JSON, default=lambda: {
        "counter_evidence": [],
        "risks": [],
        "conclusion": "",
        "ungrounded_claims_found": 0
    })

    # Arbitrator decision
    arbitrator_decision = Column(JSON, default=lambda: {
        "final_confidence": 0.0,
        "rationale": "",
        "decision": "ESCALATE",  # PROCEED, ESCALATE, BLOCK
        "weight_proposer": 0.0,
        "weight_advocate": 0.0
    })

    # Metadata
    debate_duration_ms = Column(Integer, default=0)
    escalated_to_hitl = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # (No ORM relationship: execution_id is a correlation id - the execution
    # row may not exist for gate-blocked actions.)


class ActivityFeedEvent(Base):
    """Platform-wide activity feed — replaces static dashboards with real-time events."""
    __tablename__ = 'activity_feed_events'

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)

    # Event classification
    event_type = Column(Enum(ActivityEventType), nullable=False, index=True)
    severity = Column(Enum(ActivitySeverity), default=ActivitySeverity.INFO, index=True)

    # Content
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    event_metadata = Column(JSON, default=dict)

    # Polymorphic source reference
    source_type = Column(String(32))  # blueprint, agent, skill, execution, rule, conflict, decay
    source_id = Column(String, nullable=True)

    # State
    is_read = Column(Boolean, default=False, index=True)
    requires_action = Column(Boolean, default=False, index=True)
    action_taken = Column(Boolean, default=False)
    action_taken_by = Column(String, nullable=True)
    action_taken_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
