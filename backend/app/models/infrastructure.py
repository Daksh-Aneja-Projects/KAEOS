"""
KAEOS S1 — Infrastructure Layer Models
N1: Model Management
N2: Inference Cost Governor
N3: Inter-Agent Communication Protocol
N4: Tenant Onboarding Engine
"""
from sqlalchemy import (
    Column, String, Boolean, Integer, Float, DateTime, Text, JSON, Enum, Numeric,
)
from sqlalchemy.sql import func
import uuid
import enum

from app.models.domain import Base


def _uuid():
    return str(uuid.uuid4())


# ── N1: Model Management ─────────────────────────────────────────────────────

class ModelTier(str, enum.Enum):
    FAST = "FAST"           # Haiku-class: PII classification, schema mapping, extraction
    STANDARD = "STANDARD"   # Sonnet-class: orchestration, OODA ORIENT, compliance
    DEEP = "DEEP"           # Opus-class: debate, CFO agent, ethical AI, pioneer
    VERTICAL = "VERTICAL"   # Fine-tuned domain model


class ModelRegistryEntry(Base):
    """N1 — Registered LLM model with performance benchmarks and cost profiles."""
    __tablename__ = 'model_registry'

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    model_name = Column(String, nullable=False)           # e.g. "claude-3-haiku-20240307"
    provider = Column(String(64), nullable=False)          # anthropic, groq, openai, mistral, ollama
    tier = Column(Enum(ModelTier), nullable=False)
    is_active = Column(Boolean, default=True)
    is_canary = Column(Boolean, default=False)             # A/B canary deployment

    # Performance benchmarks
    avg_latency_ms = Column(Integer, default=0)
    avg_tokens_per_task = Column(Integer, default=0)
    success_rate = Column(Float, default=1.0)
    cost_per_1k_input = Column(Float, default=0.0)
    cost_per_1k_output = Column(Float, default=0.0)

    # Routing metadata
    max_context_window = Column(Integer, default=200000)
    supports_vision = Column(Boolean, default=False)
    supports_tools = Column(Boolean, default=True)
    use_cases = Column(JSON, default=list)                 # ["extraction", "debate", "classification"]

    version = Column(String(32), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class PromptTemplate(Base):
    """N1 — Versioned prompt templates per agent and skill."""
    __tablename__ = 'prompt_templates'

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    template_key = Column(String, nullable=False, index=True)  # e.g. "debate.proposer", "extraction.articulate"
    version = Column(Integer, default=1)
    is_active = Column(Boolean, default=True)

    system_prompt = Column(Text, nullable=False)
    user_template = Column(Text, nullable=True)           # Jinja2 template with {{variables}}
    model_tier = Column(Enum(ModelTier), default=ModelTier.STANDARD)
    max_tokens = Column(Integer, default=4096)
    temperature = Column(Float, default=0.7)

    # Tracking
    usage_count = Column(Integer, default=0)
    avg_quality_score = Column(Float, default=0.0)         # 0-1 quality rating from feedback
    created_at = Column(DateTime(timezone=True), server_default=func.now())


# ── N2: Inference Cost Governor ───────────────────────────────────────────────

class TokenBudget(Base):
    """N2 — Token budget allocation per tenant, per agent, per query tier."""
    __tablename__ = 'token_budgets'

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    scope = Column(String(32), nullable=False)             # "tenant", "agent", "workflow"
    scope_id = Column(String, nullable=True)               # agent_id or workflow_id if scoped
    period = Column(String(16), default="monthly")         # "daily", "weekly", "monthly"

    # Budget limits
    token_limit = Column(Integer, default=10_000_000)       # Total tokens allowed
    token_used = Column(Integer, default=0)
    cost_limit_usd = Column(Numeric(12, 6), default=100.0)
    cost_used_usd = Column(Numeric(12, 6), default=0.0)

    # Enforcement
    soft_limit_pct = Column(Float, default=0.80)           # Warning at 80%
    hard_limit_pct = Column(Float, default=0.95)           # Degrade at 95%
    enforcement_action = Column(String(32), default="DEGRADE")  # DEGRADE, QUEUE, BLOCK

    period_start = Column(DateTime(timezone=True), server_default=func.now())
    period_end = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class CostEvent(Base):
    """N2 — Individual token consumption event for attribution."""
    __tablename__ = 'cost_events'

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    model_name = Column(String, nullable=False)
    model_tier = Column(String(32), nullable=False)

    # Attribution
    agent_id = Column(String, nullable=True)
    workflow_id = Column(String, nullable=True)
    skill_id = Column(String, nullable=True)
    # Which single decision this call belongs to. Without it, "cost per
    # decision" can only be answered as "average cost of this skill, ever" -
    # which is not the question a buyer asks. Correlation id, not an FK: the
    # cost of a gate-blocked action is real even though no execution row for
    # it will ever exist.
    execution_id = Column(String, nullable=True, index=True)
    prompt_template_key = Column(String, nullable=True)

    # Token usage
    input_tokens = Column(Integer, default=0)
    output_tokens = Column(Integer, default=0)
    total_tokens = Column(Integer, default=0)
    cost_usd = Column(Numeric(12, 6), default=0.0)
    latency_ms = Column(Integer, default=0)

    # Context
    request_type = Column(String(64))                      # "extraction", "debate", "orchestration"
    success = Column(Boolean, default=True)

    timestamp = Column(DateTime(timezone=True), server_default=func.now())


# ── N3: Inter-Agent Communication Protocol ────────────────────────────────────

class AgentMessageStatus(str, enum.Enum):
    PENDING = "PENDING"
    DELIVERED = "DELIVERED"
    PROCESSED = "PROCESSED"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"


class AgentMessage(Base):
    """N3 — Inter-agent message for async communication."""
    __tablename__ = 'agent_messages'

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)

    sender_agent_id = Column(String, nullable=False, index=True)
    receiver_agent_id = Column(String, nullable=False, index=True)
    correlation_id = Column(String, nullable=True, index=True)   # Groups related messages

    message_type = Column(String(64), nullable=False)       # "request", "response", "broadcast", "context_pass"
    payload = Column(JSON, nullable=False)
    context_envelope = Column(JSON, default=dict)            # Immutable append-only context

    status = Column(Enum(AgentMessageStatus), default=AgentMessageStatus.PENDING)
    priority = Column(Integer, default=5)                    # 1=highest, 10=lowest
    ttl_seconds = Column(Integer, default=300)               # Time to live

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    delivered_at = Column(DateTime(timezone=True), nullable=True)
    processed_at = Column(DateTime(timezone=True), nullable=True)


class AgentRegistryEntry(Base):
    """N3 — Agent discovery registry: agents register capabilities on startup."""
    __tablename__ = 'agent_registry'

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    agent_name = Column(String, nullable=False)
    agent_type = Column(String(64), nullable=False)          # "base", "specialized", "debate", "pioneer"

    capabilities = Column(JSON, default=list)                # ["extraction", "compliance_check", "report_gen"]
    model_tier_preference = Column(Enum(ModelTier), default=ModelTier.STANDARD)
    current_load = Column(Integer, default=0)
    max_concurrent = Column(Integer, default=10)
    health_status = Column(String(16), default="HEALTHY")    # HEALTHY, DEGRADED, OFFLINE
    last_heartbeat = Column(DateTime(timezone=True), nullable=True)

    # Circuit breaker state
    circuit_state = Column(String(16), default="CLOSED")     # CLOSED, OPEN, HALF_OPEN
    failure_count = Column(Integer, default=0)
    failure_threshold = Column(Integer, default=5)
    last_failure_at = Column(DateTime(timezone=True), nullable=True)

    registered_at = Column(DateTime(timezone=True), server_default=func.now())


# ── N4: Tenant Onboarding Engine ──────────────────────────────────────────────

class OnboardingStage(str, enum.Enum):
    INITIATED = "INITIATED"
    CONNECTORS_CONFIGURED = "CONNECTORS_CONFIGURED"
    SCHEMA_MAPPED = "SCHEMA_MAPPED"
    PII_CLASSIFIED = "PII_CLASSIFIED"
    FULL_CRAWL_RUNNING = "FULL_CRAWL_RUNNING"
    KG_POPULATED = "KG_POPULATED"
    CONFIDENCE_ASSIGNED = "CONFIDENCE_ASSIGNED"
    AGENTS_ACTIVATED = "AGENTS_ACTIVATED"
    ELICITATION_STARTED = "ELICITATION_STARTED"
    FULLY_ONBOARDED = "FULLY_ONBOARDED"


class TenantOnboarding(Base):
    """N4 — State machine tracking full cold-start onboarding sequence."""
    __tablename__ = 'tenant_onboarding'

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, unique=True, index=True)
    tenant_name = Column(String, nullable=False)
    industry_vertical = Column(String(64), nullable=True)  # Retail, Healthcare, Manufacturing, Financial

    # State machine
    current_stage = Column(Enum(OnboardingStage), default=OnboardingStage.INITIATED)
    stage_progress_pct = Column(Float, default=0.0)
    stages_completed = Column(JSON, default=list)           # List of completed stage names with timestamps

    # Onboarding metrics
    connectors_configured = Column(Integer, default=0)
    entities_discovered = Column(Integer, default=0)
    mappings_confirmed = Column(Integer, default=0)
    pii_fields_detected = Column(Integer, default=0)
    rules_extracted = Column(Integer, default=0)
    kg_nodes_created = Column(Integer, default=0)

    # Cold-start model pack (P5 Federated)
    model_pack_requested = Column(Boolean, default=False)
    model_pack_delivered = Column(Boolean, default=False)
    model_pack_id = Column(String, nullable=True)

    # Timeline
    initiated_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)
    estimated_completion_hours = Column(Integer, default=48)


class SchemaMapping(Base):
    """N4 — AI-proposed schema mapping between source system and Knowledge Graph."""
    __tablename__ = 'schema_mappings'

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    connector_id = Column(String, nullable=False, index=True)

    source_field = Column(String, nullable=False)
    source_object = Column(String, nullable=False)          # e.g. "Worker", "Position", "Cost Center"
    source_type = Column(String(32))                        # "string", "integer", "date", "boolean"

    target_entity = Column(String, nullable=False)          # e.g. "Employee", "OrgUnit", "Role"
    target_field = Column(String, nullable=False)

    # AI confidence
    ai_confidence = Column(Float, default=0.0)              # 0.0 - 1.0
    confidence_tier = Column(String(16))                    # GREEN (>0.85), AMBER (0.60-0.85), RED (<0.60)
    mapping_source = Column(String(32), default="AI")       # AI, MANUAL, CROSS_TENANT

    # PII classification
    is_pii = Column(Boolean, default=False)
    pii_category = Column(String(64), nullable=True)        # name, ssn, salary, health_data, biometric
    sensitivity_tier = Column(String(16), nullable=True)    # PUBLIC, INTERNAL, CONFIDENTIAL, RESTRICTED

    # Admin review
    admin_confirmed = Column(Boolean, default=False)
    confirmed_by = Column(String, nullable=True)
    confirmed_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
