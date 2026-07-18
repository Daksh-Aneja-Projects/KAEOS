"""KAEOS — Domain Models (L3 Polystore: PostgreSQL/SQLite Rules Store)"""
from sqlalchemy import (
    Column, String, Boolean, Integer, Float, DateTime, ForeignKey,
    Text, JSON, Enum,
)
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.sql import func
import uuid
import enum
try:
    from pgvector.sqlalchemy import Vector
except ImportError:
    Vector = None  # Fallback if pgvector is not installed locally


Base = declarative_base()


def _uuid():
    return str(uuid.uuid4())


class ConfidenceTier(str, enum.Enum):
    SPECULATIVE = "SPECULATIVE"
    INFERRED = "INFERRED"
    VALIDATED_PEER = "VALIDATED_PEER"
    VALIDATED_MANAGER = "VALIDATED_MANAGER"
    VALIDATED_DH = "VALIDATED_DH"
    VERIFIED = "VERIFIED"


class Rule(Base):
    __tablename__ = 'rules'

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    statement = Column(Text, nullable=False)
    trigger_json = Column(JSON, nullable=False)
    action_json = Column(JSON, nullable=False)
    exceptions_json = Column(JSON, default=list)
    domain = Column(String(64), index=True)
    workflow_id = Column(String, ForeignKey('workflows.id'), nullable=True)

    # 5-Dimensional Confidence Vector (stored as JSON)
    confidence_vector = Column(JSON, default=lambda: {
        "source_breadth": 0.0,
        "source_authority": 0.0,
        "temporal_freshness": 1.0,
        "outcome_validation": 0.5,
        "explicit_validation": 0.0
    })
    confidence_scalar = Column(Float, default=0.0)
    confidence_tier = Column(
        Enum(ConfidenceTier), default=ConfidenceTier.SPECULATIVE
    )

    half_life_days = Column(Integer, default=180)
    is_executable = Column(Boolean, default=False)
    is_archived = Column(Boolean, default=False)
    version = Column(Integer, default=1)
    parent_version = Column(String, ForeignKey('rules.id'), nullable=True)

    source_signals = Column(JSON, default=list)
    validated_by = Column(JSON, default=list)
    compliance_tags = Column(JSON, default=list)
    access_level = Column(String(16), default='department')

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    validated_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    last_decay_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    guardrails = relationship("RuleGuardrail", back_populates="rule", lazy="selectin")
    # Explicit view-only join: ProvenanceLedger.rule_id is a polymorphic
    # subject id (no FK), so SQLAlchemy cannot infer the join.
    provenance_entries = relationship(
        "ProvenanceLedger",
        primaryjoin="Rule.id == foreign(ProvenanceLedger.rule_id)",
        viewonly=True,
        lazy="selectin",
    )
    workflow = relationship("Workflow", back_populates="rules")


class RuleEmbedding(Base):
    """Vector storage for rules, used in L3 Polystore"""
    __tablename__ = 'rule_embeddings'

    rule_id = Column(String, primary_key=True)
    tenant_id = Column(String, nullable=False, index=True)
    # text-embedding-3-small dimension is 1536
    # only define the column if pgvector is installed
    if Vector:
        embedding = Column(Vector(1536))
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

class SkillEmbedding(Base):
    """Vector storage for skills, used in L9 SkillRouter fuzzy matching"""
    __tablename__ = 'skill_embeddings'

    skill_db_id = Column(String, primary_key=True)
    tenant_id = Column(String, nullable=False, index=True)
    if Vector:
        embedding = Column(Vector(1536))
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class RuleGuardrail(Base):
    __tablename__ = 'rule_guardrails'

    id = Column(String, primary_key=True, default=_uuid)
    rule_id = Column(String, ForeignKey('rules.id'), index=True)
    guardrail_type = Column(String(32))  # PRE_CHECK, POST_CHECK, RATE_LIMIT
    condition = Column(JSON)
    action_on_fail = Column(String(32))  # BLOCK, WARN, ESCALATE

    rule = relationship("Rule", back_populates="guardrails")


class ProvenanceLedger(Base):
    __tablename__ = 'provenance_ledger'

    id = Column(String, primary_key=True, default=_uuid)
    # The tenant this ledger entry belongs to. The ledger used to carry no
    # tenant_id at all - the subject was inferred from the polymorphic rule_id -
    # so /provenance could not be tenant-scoped and RLS had nothing to filter on.
    # Nullable only so pre-existing rows (written before this column) don't block
    # the migration; every new write populates it.
    tenant_id = Column(String, index=True, nullable=True)
    # Polymorphic subject id, NOT a foreign key: the ledger records rule
    # events (rule ids) AND agent executions (skill ids). Postgres enforced
    # the old rules FK and rejected every AGENT_EXECUTION entry (SQLite
    # masked it - FK enforcement off by default).
    rule_id = Column(String, index=True)
    event_type = Column(String(32), nullable=False)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
    actor_hash = Column(String(64))
    actor_role = Column(String(64))
    evidence_ids = Column(JSON, default=list)
    confidence_at = Column(Float)
    reasoning = Column(Text)
    parent_id = Column(String, ForeignKey('provenance_ledger.id'))
    # 128 chars: the standard chain uses sha256 (64 hex) but the quantum
    # ledger writes sha3_512 (128 hex) to this same column. Postgres rejects
    # the overflow (StringDataRightTruncationError); SQLite truncated silently,
    # so every federated/quantum export was corrupt-but-quiet in dev.
    chain_hash = Column(String(128), unique=True)

    rule = relationship(
        "Rule",
        primaryjoin="foreign(ProvenanceLedger.rule_id) == Rule.id",
        viewonly=True,
    )


class ConfidenceHistory(Base):
    __tablename__ = 'confidence_history'

    id = Column(String, primary_key=True, default=_uuid)
    rule_id = Column(String, ForeignKey('rules.id'), index=True)
    confidence_old = Column(Float)
    confidence_new = Column(Float)
    reason = Column(String(64))
    changed_by = Column(String(64))
    changed_at = Column(DateTime(timezone=True), server_default=func.now())


class Signal(Base):
    """L1 — Structured Signal from Ingestion Pipeline"""
    __tablename__ = 'signals'

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    source_type = Column(String(32))     # messaging, helpdesk, issue_tracker, etc.
    source_entity = Column(String)       # channel_id, ticket_id
    signal_type = Column(String(32))     # DECISION, APPROVAL, EXCEPTION, etc.
    domain = Column(String(64), index=True)
    clean_payload = Column(Text)
    authority_score = Column(Float, default=0.5)
    novelty_score = Column(Float, default=0.5)
    temporal_class = Column(String(32))  # HISTORICAL, CURRENT, RECURRING
    entities = Column(JSON, default=list)
    pii_present = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    processed_at = Column(DateTime(timezone=True), nullable=True, index=True)  # Set when PreCog consumes signal




class Workflow(Base):
    """L3 — Workflow node in Knowledge Graph"""
    __tablename__ = 'workflows'

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    name = Column(String, nullable=False)
    department = Column(String(64), index=True)
    sla_hours = Column(Integer, default=48)
    coverage_score = Column(Float, default=0.0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    rules = relationship("Rule", back_populates="workflow")


class Skill(Base):
    """L8 — Compiled Skill Contract"""
    __tablename__ = 'skills'

    id = Column(String, primary_key=True, default=_uuid)
    skill_id = Column(String, unique=True, nullable=False, index=True)
    tenant_id = Column(String, nullable=False, index=True)
    department = Column(String(64), index=True)
    domain = Column(String(64))
    version = Column(String(16))
    status = Column(String(32), default="ACTIVE")  # ACTIVE, EXPIRING_SOON, ARCHIVED, DRAFT

    # Confidence metadata
    confidence = Column(Float, default=0.0)
    confidence_tier = Column(String(64))
    confidence_vector = Column(JSON, default=dict)

    # Execution stats
    execution_count = Column(Integer, default=0)
    success_rate = Column(Float, default=0.0)
    half_life_days = Column(Integer, default=90)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    last_validated = Column(DateTime(timezone=True), nullable=True)

    # Skill content (YAML contract body)
    triggers = Column(JSON, default=list)
    steps = Column(JSON, default=list)
    exceptions = Column(JSON, default=list)
    guardrails = Column(JSON, default=dict)
    mcp_tool_bindings = Column(JSON, default=list)
    compliance_tags = Column(JSON, default=list)
    confidence_notes = Column(JSON, default=list)
    provenance = Column(JSON, default=dict)
    access_level = Column(String(32), default="department")

    compiled_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    executions = relationship("SkillExecution", back_populates="skill", lazy="selectin")


class SkillExecution(Base):
    """L9/L10 — Agent Execution Record"""
    __tablename__ = 'skill_executions'

    id = Column(String, primary_key=True, default=_uuid)
    skill_db_id = Column(String, ForeignKey('skills.id'), index=True)
    skill_id_name = Column(String, index=True)
    tenant_id = Column(String, nullable=False, index=True)

    # Execution metadata
    status = Column(String(32))   # SUCCESS_CLEAN, FAILED_RULE_MISMATCH, HUMAN_OVERRIDDEN, etc.
    route_type = Column(String(16))  # SKILL_EXEC, RAG_EXEC
    agent_state = Column(String(32), default="IDLE")

    # Context
    task_intent = Column(Text)
    context = Column(JSON, default=dict)
    reasoning_chain = Column(JSON, default=list)

    # Timing
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)
    duration_ms = Column(Integer, default=0)

    # HITL
    hitl_required = Column(Boolean, default=False)
    hitl_approved = Column(Boolean, nullable=True)
    hitl_approver = Column(String, nullable=True)

    # Outcome
    outcome_type = Column(String(32))  # SUCCESS_CLEAN, SUCCESS_WITH_EDIT, HUMAN_OVERRIDDEN, etc.
    confidence_delta = Column(Float, default=0.0)

    skill = relationship("Skill", back_populates="executions")


class Employee(Base):
    """L5 — Employee for Elicitation Engine"""
    __tablename__ = 'employees'

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    hashed_id = Column(String(64), unique=True)
    display_name = Column(String)
    role = Column(String(64))
    department = Column(String(64), index=True)
    tenure_months = Column(Integer, default=0)
    authority_score = Column(Float, default=0.5)
    expertise_domains = Column(JSON, default=list)
    response_rate = Column(Float, default=0.0)

    # Knowledge Reputation (L6 — Employee Trust)
    total_contributions = Column(Integer, default=0)
    confirmed_contributions = Column(Integer, default=0)
    rejected_contributions = Column(Integer, default=0)
    reputation_score = Column(Float, default=0.5)

    # Elicitation state
    questions_this_week = Column(Integer, default=0)
    last_question_at = Column(DateTime(timezone=True), nullable=True)

    questions = relationship("ElicitationQuestion", back_populates="employee", lazy="selectin")


class ElicitationQuestion(Base):
    """L5 — Elicitation Question"""
    __tablename__ = 'elicitation_questions'

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    employee_id = Column(String, ForeignKey('employees.id'), index=True)

    question_text = Column(Text, nullable=False)
    question_type = Column(String(32))  # GAP_FILL, CONTRADICTION, DECAY_REVALIDATION, ARTICULATION
    context_ref = Column(String)  # ticket_id, slack_thread, etc.
    priority = Column(String(16), default="NORMAL")  # HIGH, NORMAL, LOW
    delivery_channel = Column(String(16), default="slack")

    # Quality scores
    specificity = Column(Float, default=0.0)
    groundedness = Column(Float, default=0.0)
    answerability = Column(Float, default=0.0)

    # State
    status = Column(String(16), default="PENDING")  # PENDING, ANSWERED, SKIPPED, EXPIRED
    answer_text = Column(Text, nullable=True)
    answered_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    employee = relationship("Employee", back_populates="questions")


class Connector(Base):
    """L0 — Enterprise Integration Connector (Data Fabric Connector Mesh)"""
    __tablename__ = 'connectors'

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    name = Column(String, nullable=False)           # "Slack", "Microsoft Teams", etc.
    category = Column(String(64))                    # communications, crm, hris, engineering, support, commercial
    connector_type = Column(String(32))              # NATIVE, WEBHOOK, API, CDC
    status = Column(String(32), default="AVAILABLE") # AVAILABLE, CONNECTED, SYNCING, ERROR, PAUSED
    icon = Column(String(32))                        # emoji or icon key
    description = Column(Text)

    # Connection config
    auth_method = Column(String(32))                 # oauth2, api_key, service_account, webhook
    api_endpoint = Column(String)
    sync_frequency = Column(String(32), default="REAL_TIME")  # REAL_TIME, HOURLY, DAILY
    last_sync_at = Column(DateTime(timezone=True), nullable=True)

    # Stats
    events_ingested = Column(Integer, default=0)
    signals_extracted = Column(Integer, default=0)
    error_count = Column(Integer, default=0)
    avg_latency_ms = Column(Integer, default=0)

    # PII scrubbing
    pii_scrub_enabled = Column(Boolean, default=True)
    pii_entities_found = Column(Integer, default=0)

    connected_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class ConnectorCredential(Base):
    """L0 — Stored live-integration credentials for a connector.

    `config` holds non-secret connection settings (base URLs, query filters);
    `secrets_encrypted` holds the Fernet-encrypted secret material (tokens,
    passwords, client secrets). Plaintext secrets are never persisted.
    """
    __tablename__ = 'connector_credentials'

    connector_id = Column(String, ForeignKey('connectors.id'), primary_key=True)
    tenant_id = Column(String, nullable=False, index=True)
    provider = Column(String(32), nullable=False)   # jira, salesforce, workday, sap, generic_rest
    config = Column(JSON, default=dict)
    secrets_encrypted = Column(Text, nullable=False)
    last_test_ok = Column(Boolean, nullable=True)
    last_test_detail = Column(Text, nullable=True)
    last_tested_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ConflictCase(Base):
    """L16 — Conflict Resolution Arena"""
    __tablename__ = 'conflict_cases'

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    rule_a_id = Column(String, ForeignKey('rules.id'), nullable=False)
    rule_b_id = Column(String, ForeignKey('rules.id'), nullable=False)
    conflict_type = Column(String(32))  # DIRECT_CONTRADICTION, SCOPE_OVERLAP, TEMPORAL_SUPERSESSION
    severity = Column(String(16))       # CRITICAL, MODERATE, MINOR
    status = Column(String(32), default="OPEN")  # OPEN, IN_REVIEW, RESOLVED, ESCALATED
    resolution_type = Column(String(32), nullable=True)  # CHOOSE_A, CHOOSE_B, MERGE, SUPERSEDE, NEW_RULE
    resolution_note = Column(Text, nullable=True)
    assigned_to = Column(String, nullable=True)
    deadline = Column(DateTime(timezone=True), nullable=True)

    detected_at = Column(DateTime(timezone=True), server_default=func.now())
    resolved_at = Column(DateTime(timezone=True), nullable=True)

    rule_a = relationship("Rule", foreign_keys=[rule_a_id])
    rule_b = relationship("Rule", foreign_keys=[rule_b_id])


class MarketplaceTemplate(Base):
    """L19 — Developer Platform & Skills Marketplace"""
    __tablename__ = 'marketplace_templates'

    id = Column(String, primary_key=True, default=_uuid)
    name = Column(String, nullable=False)
    category = Column(String(64))      # Sales, Support, Finance, HR, Engineering, Legal
    description = Column(Text)
    author = Column(String)
    version = Column(String(16), default="1.0")
    rating = Column(Float, default=0.0)
    installs = Column(Integer, default=0)
    rules_count = Column(Integer, default=0)
    skills_count = Column(Integer, default=0)
    tags = Column(JSON, default=list)
    compliance_frameworks = Column(JSON, default=list)
    status = Column(String(32), default="PUBLISHED")  # PUBLISHED, DRAFT, DEPRECATED
    certified = Column(Boolean, default=False)
    preview_data = Column(JSON, default=dict)

    created_at = Column(DateTime(timezone=True), server_default=func.now())


class SecurityAuditLog(Base):
    """L17 — Security, Access Control & Zero-Trust Fabric"""
    __tablename__ = 'security_audit_logs'

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    event_type = Column(String(64))    # ACCESS, MODIFICATION, QUERY, AUTH_FAILURE, EXPORT, AGENT_EXEC
    actor_hash = Column(String(64))
    actor_role = Column(String(64))
    resource_type = Column(String(32)) # RULE, SKILL, EXECUTION, PROVENANCE, EXPORT
    resource_id = Column(String, nullable=True)
    action = Column(String(32))        # READ, WRITE, DELETE, EXECUTE, EXPORT
    result = Column(String(16))        # ALLOWED, BLOCKED, ESCALATED
    ip_address = Column(String(45), nullable=True)
    details = Column(JSON, default=dict)

    timestamp = Column(DateTime(timezone=True), server_default=func.now())


class DecayEvent(Base):
    """L7 — Temporal Knowledge Decay Events (TimescaleDB equivalent)"""
    __tablename__ = 'decay_events'

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    rule_id = Column(String, ForeignKey('rules.id'), index=True)
    event_type = Column(String(32))    # SCHEDULED_DECAY, TRIGGER_INVALIDATION, MANUAL_RESET, RESTORED
    trigger_source = Column(String(64), nullable=True)  # org_chart_change, pricing_update, etc.
    confidence_before = Column(Float)
    confidence_after = Column(Float)
    half_life_days = Column(Integer)
    days_since_validation = Column(Integer)
    action_taken = Column(String(32))  # DECAY_APPLIED, PAUSED_SKILL, ELICITATION_TRIGGERED, ARCHIVED

    timestamp = Column(DateTime(timezone=True), server_default=func.now())

    rule = relationship("Rule")


class RedTeamScanResult(Base):
    """L12 — Adversarial Testing & Red-Team Harness"""
    __tablename__ = 'redteam_scan_results'

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    skill_id = Column(String, index=True)
    skill_department = Column(String(64))
    scan_type = Column(String(32))     # BOUNDARY, ADVERSARIAL, CONFIDENCE_BOUNDARY, STALE_DATA, CROSS_SKILL
    status = Column(String(16))        # PASSED, FAILED, WARNING
    vulnerabilities_found = Column(Integer, default=0)
    details = Column(JSON, default=list)  # list of vulnerability objects
    confidence_at_scan = Column(Float)
    duration_ms = Column(Integer, default=0)

    scanned_at = Column(DateTime(timezone=True), server_default=func.now())
