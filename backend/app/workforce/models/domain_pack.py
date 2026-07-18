"""
KAEOS Workforce Layer — Domain Pack Models

A DomainPack is a packaged department template that defines everything
needed to deploy a digital department: capabilities, agents, processes,
integrations, knowledge templates, and compliance requirements.

Packs are loaded from YAML files on disk (built-in) or installed from
the marketplace (custom). Per-tenant installation state is tracked in
DomainPackInstallation.
"""
from sqlalchemy import (
    Column, String, Integer, Float, DateTime, Text, JSON,
    Enum, ForeignKey, UniqueConstraint,
)
from sqlalchemy.sql import func
import uuid
import enum

from app.models.domain import Base


def _uuid():
    return str(uuid.uuid4())


class DomainPackSource(str, enum.Enum):
    BUILT_IN = "BUILT_IN"           # Ships with KAEOS
    MARKETPLACE = "MARKETPLACE"     # Installed from marketplace
    CUSTOM = "CUSTOM"               # Created by tenant


class InstallationStatus(str, enum.Enum):
    INSTALLED = "INSTALLED"
    UPDATING = "UPDATING"
    UNINSTALLED = "UNINSTALLED"
    FAILED = "FAILED"


class DomainPack(Base):
    """
    Packaged department template — the blueprint for deploying an
    entire digital department.

    A DomainPack is the product concept: "HR-in-a-box", "Finance-in-a-box".
    It defines:
    - What capabilities the department has (e.g., Talent Acquisition, Benefits)
    - What agents are needed per capability
    - What processes each capability executes
    - What integrations are required/optional
    - What knowledge templates to seed
    - What compliance frameworks apply
    """
    __tablename__ = "domain_packs"

    id = Column(String, primary_key=True, default=_uuid)

    # Identity
    name = Column(String(128), nullable=False)               # "Human Resources"
    slug = Column(String(64), nullable=False, unique=True)    # "hr"
    description = Column(Text, nullable=True)
    long_description = Column(Text, nullable=True)           # Full marketing description
    icon = Column(String(16), default="📦")
    category = Column(String(64), nullable=False)             # "people", "finance", "operations"
    industry_verticals = Column(JSON, default=list)           # ["all"] or ["healthcare", "finance"]

    # Version
    version = Column(String(32), default="1.0.0")
    changelog = Column(Text, nullable=True)

    # Source
    source = Column(Enum(DomainPackSource), default=DomainPackSource.BUILT_IN)
    author = Column(String(128), default="KAEOS")
    author_url = Column(String(256), nullable=True)

    # Pack contents (the full definition)
    required_integrations = Column(JSON, default=list)
    # Schema: [{"category": "hris", "examples": ["workday", "bamboohr"], "data_provided": ["employee_records"]}]

    optional_integrations = Column(JSON, default=list)
    # Same schema as required_integrations

    capabilities = Column(JSON, default=list)
    # Schema: [{"id": "talent_acquisition", "name": "Talent Acquisition", "description": "...",
    #           "processes": [...], "agents": [...], "compliance": [...]}]

    agent_definitions = Column(JSON, default=list)
    # Schema: [{"name": "RecruitingAgent", "type": "recruiting", "capability": "talent_acquisition",
    #           "description": "...", "skills": [...], "persona": "..."}]

    process_definitions = Column(JSON, default=list)
    # Schema: [{"id": "candidate_screening", "name": "...", "capability": "talent_acquisition",
    #           "steps": [...], "sla_hours": 48}]

    knowledge_templates = Column(JSON, default=list)
    # Schema: ["employee_handbook", "pto_policy", "benefits_guide"]

    # Deployment configuration
    deployment_config = Column(JSON, default=dict)
    # Schema: {"min_agents": 4, "max_agents": 12, "default_confidence_floor": 0.75,
    #          "requires_hitl": true, "compliance_frameworks": ["EEOC", "GDPR"]}

    compliance_frameworks = Column(JSON, default=list)       # ["EEOC", "GDPR", "CCPA"]

    # Stats
    install_count = Column(Integer, default=0)
    rating = Column(Float, default=0.0)
    rating_count = Column(Integer, default=0)

    # Status
    status = Column(String(16), default="ACTIVE")            # ACTIVE, DEPRECATED, DRAFT

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class DomainPackInstallation(Base):
    """
    Per-tenant installation tracking for domain packs.

    When a tenant installs a domain pack, this record tracks:
    - Which version is installed
    - Any tenant-specific customizations
    - Installation status
    """
    __tablename__ = "domain_pack_installations"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    domain_pack_id = Column(String, ForeignKey("domain_packs.id"), nullable=False, index=True)

    # Version
    installed_version = Column(String(32), nullable=False)
    available_version = Column(String(32), nullable=True)    # Set when update is available

    # Status
    status = Column(Enum(InstallationStatus), default=InstallationStatus.INSTALLED)

    # Customizations (tenant-specific overrides)
    customizations = Column(JSON, default=dict)
    # Schema: {"disabled_capabilities": [], "custom_agents": [], "config_overrides": {}}

    # Deployment reference
    department_id = Column(String, ForeignKey("departments.id"), nullable=True)

    installed_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("tenant_id", "domain_pack_id", name="uq_pack_install_tenant"),
    )
