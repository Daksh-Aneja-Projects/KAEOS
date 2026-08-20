"""
KAEOS Workforce Layer — Core Models

Department → Capability → BusinessProcess → DepartmentAgent

These are the enterprise-first abstractions that sit above the existing
KAEOS agent layer. A Department owns Capabilities, which contain
BusinessProcesses executed by DepartmentAgents (which reference
underlying DeployedAgents from the AEOS layer).
"""
from sqlalchemy import (
    Column, String, Integer, Float, DateTime, Text, JSON,
    Enum, ForeignKey, UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum

from app.models.domain import Base
from app.models.mixins import new_uuid as _uuid




# ── Measurement honesty contract ──────────────────────────────────────────────
# Hours-saved (and any cost figure derived from it) cannot be computed by KAEOS.
# It requires two tenant inputs the platform has no way to observe: how long the
# task took a human before automation, and that human's loaded hourly cost. Both
# were once faked - `tasks * 0.5` hours, multiplied by a hardcoded rate - which
# produced a confident ROI number with no basis behind it.
#
# The rule, platform-wide: report `None` plus this note. Never a bare `0`, which
# a reader would take to mean "measured, and it saved nothing". Every surface
# that exposes hours-saved or a cost derived from it imports these two symbols,
# so the contract is stated once and cannot drift per-endpoint again.
#
# To make the number real, a tenant supplies a per-skill human baseline and rate;
# the readers then surface the stored value instead of None. See
# `hours_saved_basis` on each response for which of the two states is in play.
HOURS_SAVED_NOTE = (
    "Requires a human-baseline duration and loaded hourly rate per skill "
    "(tenant inputs KAEOS cannot measure). Reported as null rather than estimated."
)
HOURS_SAVED_BASIS_UNSET = "no_tenant_baseline"
HOURS_SAVED_BASIS_TENANT = "tenant_supplied"


def hours_saved_payload(
    hours: float | None,
    loaded_rate: float | None = None,
    tenant_cost: float | None = None,
) -> dict:
    """Build the standard hours-saved/cost-saved block for an API response.

    Both inputs are tenant-supplied or absent; KAEOS derives neither.

    * ``hours`` - a stored human-baseline figure (``Department.hours_saved_total``
      or ``WorkforceMetrics.hours_saved_estimate``).
    * ``tenant_cost`` - a stored cost figure (``WorkforceMetrics.cost_savings_estimate``),
      for tenants that track cost directly rather than via hours.

    Cost is reported when the tenant supplied it, or derived from hours that are
    themselves real. It is never derived from absent hours: multiplying a
    fabricated ``tasks * 0.5`` by a hardcoded rate was the original defect, two
    fabrications stacked into a confident ROI number with nothing behind it.

    The two figures are independent. A tenant tracking cost but not hours gets a
    real ``cost_saved`` alongside a null ``hours_saved``, rather than losing both.
    """
    has_hours = bool(hours and hours > 0)
    has_cost = bool(tenant_cost and tenant_cost > 0)

    if has_cost:
        cost = round(tenant_cost, 2)
    elif has_hours and loaded_rate:
        cost = round(hours * loaded_rate, 2)
    else:
        cost = None

    if not has_hours and not has_cost:
        return {
            "hours_saved": None,
            "cost_saved": None,
            "hours_saved_basis": HOURS_SAVED_BASIS_UNSET,
            "hours_saved_note": HOURS_SAVED_NOTE,
        }

    return {
        "hours_saved": round(hours, 1) if has_hours else None,
        "cost_saved": cost,
        "hours_saved_basis": HOURS_SAVED_BASIS_TENANT,
        # A tenant tracking cost only still gets told why hours is null.
        "hours_saved_note": None if has_hours else HOURS_SAVED_NOTE,
    }


# ── Enums ─────────────────────────────────────────────────────────────────────

class DepartmentStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    DEPLOYING = "DEPLOYING"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    DEGRADED = "DEGRADED"
    ARCHIVED = "ARCHIVED"


class CapabilityStatus(str, enum.Enum):
    PLANNED = "PLANNED"
    DEPLOYING = "DEPLOYING"
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"
    DEGRADED = "DEGRADED"


class DeploymentStatus(str, enum.Enum):
    INIT = "INIT"
    PACK_SELECTED = "PACK_SELECTED"
    SYSTEMS_CONNECTING = "SYSTEMS_CONNECTING"
    INTEGRATIONS_MAPPING = "INTEGRATIONS_MAPPING"
    WORKFORCE_GENERATING = "WORKFORCE_GENERATING"
    AGENTS_DEPLOYING = "AGENTS_DEPLOYING"
    KNOWLEDGE_SEEDING = "KNOWLEDGE_SEEDING"
    RUNTIME_STARTING = "RUNTIME_STARTING"
    ACTIVE = "ACTIVE"
    FAILED = "FAILED"
    ROLLED_BACK = "ROLLED_BACK"


# ── Department ────────────────────────────────────────────────────────────────

class Department(Base):
    """
    Top-level deployed business unit — the primary entity in the
    Enterprise Workforce Operating System.

    A Department represents a complete digital version of a real business
    function (HR, Finance, Legal, etc.). It owns capabilities, agents,
    processes, and metrics. Users see and interact with Departments —
    never with raw agents or blueprints.
    """
    __tablename__ = "departments"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)

    # Identity
    name = Column(String(128), nullable=False)              # "Human Resources"
    slug = Column(String(64), nullable=False)                # "hr"
    description = Column(Text, nullable=True)
    icon = Column(String(16), default="🏢")                 # Emoji icon

    # Source
    domain_pack_id = Column(String, ForeignKey("domain_packs.id"), nullable=True)
    domain_pack_version = Column(String(32), nullable=True)

    # Status
    status = Column(Enum(DepartmentStatus), default=DepartmentStatus.DRAFT, index=True)

    # Scale
    employee_count = Column(Integer, default=0)              # How many employees this dept serves
    agent_count = Column(Integer, default=0)                 # How many agents are deployed
    capability_count = Column(Integer, default=0)            # Active capabilities
    process_count = Column(Integer, default=0)               # Defined processes

    # Configuration
    deployment_config = Column(JSON, default=dict)           # Department-specific settings
    connected_systems = Column(JSON, default=list)           # List of connector_ids
    compliance_frameworks = Column(JSON, default=list)       # ["EEOC", "GDPR", "SOX"]

    # Metrics (denormalized for dashboard performance)
    health_score = Column(Float, default=1.0)                # 0.0-1.0 aggregate health
    automation_coverage = Column(Float, default=0.0)         # % of processes automated
    tasks_completed_total = Column(Integer, default=0)
    # Tenant-supplied ONLY. Nothing in KAEOS derives this: see HOURS_SAVED_NOTE.
    # A 0.0 here means "no baseline configured", NOT "no time was saved", so
    # readers must report null-with-note rather than a bare 0.
    hours_saved_total = Column(Float, default=0.0)

    # Lifecycle
    deployed_at = Column(DateTime(timezone=True), nullable=True)
    paused_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    capabilities = relationship("Capability", back_populates="department", cascade="all, delete-orphan")
    department_agents = relationship("DepartmentAgent", back_populates="department", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("tenant_id", "slug", name="uq_department_tenant_slug"),
    )


# ── Capability ────────────────────────────────────────────────────────────────

class Capability(Base):
    """
    Business capability within a department.

    Example: "Talent Acquisition" under HR, or "Accounts Payable" under Finance.
    A capability groups related processes and agents. It's the middle layer
    of the hierarchy: Department → Capability → Process.
    """
    __tablename__ = "capabilities"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    department_id = Column(String, ForeignKey("departments.id"), nullable=False, index=True)

    # Identity
    name = Column(String(128), nullable=False)               # "Talent Acquisition"
    slug = Column(String(64), nullable=False)                 # "talent_acquisition"
    description = Column(Text, nullable=True)
    icon = Column(String(16), default="⚡")

    # Status
    status = Column(Enum(CapabilityStatus), default=CapabilityStatus.PLANNED, index=True)

    # Configuration
    agent_definitions = Column(JSON, default=list)           # Agent configs from domain pack
    process_definitions = Column(JSON, default=list)         # Process configs from domain pack
    required_integrations = Column(JSON, default=list)       # Integration categories needed
    compliance_tags = Column(JSON, default=list)             # Compliance requirements

    # Metrics (denormalized)
    automation_pct = Column(Float, default=0.0)              # % automated vs human
    tasks_completed = Column(Integer, default=0)
    active_agents = Column(Integer, default=0)

    # Lifecycle
    activated_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    department = relationship("Department", back_populates="capabilities")
    processes = relationship("BusinessProcess", back_populates="capability", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("department_id", "slug", name="uq_capability_dept_slug"),
    )


# ── Business Process ──────────────────────────────────────────────────────────

class BusinessProcess(Base):
    """
    Executable business process within a capability.

    Example: "Candidate Screening" under "Talent Acquisition".
    Contains a process graph (DAG of steps) that the ProcessEngine can execute.
    Steps can be agent actions, human checkpoints, decisions, or notifications.
    """
    __tablename__ = "business_processes"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    capability_id = Column(String, ForeignKey("capabilities.id"), nullable=False, index=True)
    department_id = Column(String, ForeignKey("departments.id"), nullable=False, index=True)

    # Identity
    name = Column(String(128), nullable=False)               # "Candidate Screening"
    slug = Column(String(64), nullable=False)                 # "candidate_screening"
    description = Column(Text, nullable=True)

    # Process definition
    process_graph = Column(JSON, default=dict)               # React Flow compatible {nodes, edges}
    steps = Column(JSON, default=list)                       # Ordered step definitions
    trigger_type = Column(String(32), default="MANUAL")      # MANUAL, EVENT, SCHEDULE, API
    trigger_config = Column(JSON, default=dict)              # Trigger-specific configuration

    # SLA
    sla_hours = Column(Float, nullable=True)                 # Target completion time
    escalation_after_hours = Column(Float, nullable=True)    # Auto-escalate if exceeded

    # Metrics (denormalized)
    automation_pct = Column(Float, default=0.0)
    execution_count = Column(Integer, default=0)
    avg_duration_ms = Column(Integer, default=0)
    success_rate = Column(Float, default=0.0)
    last_executed_at = Column(DateTime(timezone=True), nullable=True)

    # Status
    status = Column(String(16), default="ACTIVE")            # ACTIVE, DISABLED, DRAFT
    version = Column(Integer, default=1)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    capability = relationship("Capability", back_populates="processes")

    __table_args__ = (
        UniqueConstraint("capability_id", "slug", name="uq_process_capability_slug"),
    )


# ── Department Agent (Junction) ───────────────────────────────────────────────

class DepartmentAgent(Base):
    """
    Maps a deployed KAEOS agent to a department and capability.

    This is the bridge between the existing agent layer (DeployedAgent from
    agent_factory.py) and the new workforce layer. It adds department context
    to an agent — what role does it play, which capability does it serve.
    """
    __tablename__ = "department_agents"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    department_id = Column(String, ForeignKey("departments.id"), nullable=False, index=True)
    capability_id = Column(String, ForeignKey("capabilities.id"), nullable=True, index=True)

    # Reference to existing KAEOS agent. Constraint names mirror migration 0055
    # so the drift gate sees one FK each, not two differently-named copies.
    deployed_agent_id = Column(
        String, ForeignKey("deployed_agents.id", name="fk_department_agents_deployed_agent_id"),
        nullable=True, index=True)
    blueprint_id = Column(
        String, ForeignKey("agent_blueprints.id", name="fk_department_agents_blueprint_id"),
        nullable=True)

    # Department context
    agent_name = Column(String(128), nullable=False)         # "RecruitingAgent"
    agent_type = Column(String(64), nullable=False)          # "recruiting", "benefits", "compliance"
    role_in_department = Column(String(128), nullable=True)   # "Manages recruiting pipeline"
    persona = Column(Text, nullable=True)                    # System prompt for this agent

    # Configuration
    agent_config = Column(JSON, default=dict)                # Agent-specific configuration
    skills = Column(JSON, default=list)                      # List of skill identifiers
    compliance_tags = Column(JSON, default=list)

    # Status
    status = Column(String(16), default="ACTIVE")            # ACTIVE, PAUSED, DEGRADED, OFFLINE
    health_score = Column(Float, default=1.0)
    tasks_handled = Column(Integer, default=0)
    last_active_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    department = relationship("Department", back_populates="department_agents")


# ── Workforce Deployment (State Machine Record) ──────────────────────────────

class WorkforceDeployment(Base):
    """
    Tracks the full deployment lifecycle of a department.

    Each deployment is a state machine that progresses through stages:
    INIT → PACK_SELECTED → SYSTEMS_CONNECTING → INTEGRATIONS_MAPPING →
    WORKFORCE_GENERATING → AGENTS_DEPLOYING → KNOWLEDGE_SEEDING →
    RUNTIME_STARTING → ACTIVE

    Failed deployments record error logs and can be rolled back.
    """
    __tablename__ = "workforce_deployments"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    department_id = Column(String, ForeignKey("departments.id"), nullable=True, index=True)

    # Source
    domain_pack_id = Column(String, ForeignKey("domain_packs.id"), nullable=True)
    domain_pack_slug = Column(String(64), nullable=True)

    # State Machine
    status = Column(Enum(DeploymentStatus), default=DeploymentStatus.INIT, index=True)
    current_step = Column(String(64), default="init")
    progress_pct = Column(Float, default=0.0)                # 0.0-100.0

    # Configuration (captured at deploy time)
    selected_capabilities = Column(JSON, default=list)       # Which capabilities to enable
    connected_systems = Column(JSON, default=list)           # Connector IDs to use
    employee_count = Column(Integer, default=0)
    deployment_options = Column(JSON, default=dict)           # Extra config

    # Step log — append-only timeline
    deployment_steps = Column(JSON, default=list)
    # Schema: [{"step": "PACK_SELECTED", "status": "COMPLETED", "started_at": "...", "completed_at": "...", "details": {...}}]

    # Results
    agents_created = Column(JSON, default=list)              # List of DepartmentAgent IDs
    blueprints_created = Column(JSON, default=list)          # List of blueprint IDs
    capabilities_activated = Column(JSON, default=list)      # List of capability IDs
    processes_created = Column(JSON, default=list)           # List of process IDs

    # Error tracking
    error_log = Column(JSON, default=list)
    # Schema: [{"step": "...", "error": "...", "timestamp": "...", "recoverable": true}]

    # Lifecycle
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)
    rolled_back_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
