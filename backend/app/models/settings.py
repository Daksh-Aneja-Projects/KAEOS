"""KAEOS — Platform Settings Models"""
from sqlalchemy import Column, String, Boolean, Integer, JSON, DateTime, UniqueConstraint
from sqlalchemy.sql import func
import uuid

from app.models.domain import Base

def _uuid():
    return str(uuid.uuid4())

class TenantLLMConfig(Base):
    """
    Per-tenant BYOK model routing. Supersedes the old LLMRoutingConfig, which
    had `layer` globally unique (one tenant's config blocked every other tenant)
    and stored the API key in plaintext, returning it from a non-tenant-scoped
    GET. Keys here are Fernet-encrypted at rest and never serialized back out.
    """
    __tablename__ = 'tenant_llm_configs'
    __table_args__ = (
        UniqueConstraint('tenant_id', 'layer', name='uq_tenant_llm_layer'),
    )

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    layer = Column(String(32), nullable=False)  # TIER_1_COMPLEX | TIER_2_STANDARD | TIER_3_FAST | TIER_EMBEDDING
    model_name = Column(String(128), nullable=False)
    provider = Column(String(32), nullable=False)

    # Fernet token (encrypt_secrets); never returned by the API.
    api_key_encrypted = Column(String, nullable=True)
    api_base = Column(String(256), nullable=True)  # self-hosted / custom OpenAI-compatible

    # Capability profile written by the model probe — drives gate adaptation.
    # {"json_compliance": 0-1, "reasoning_depth": 0-1, "instruction_following": 0-1,
    #  "latency_ms": int, "context_length": int, "probed_at": iso, "tier_ceiling": 0-1}
    capability_profile = Column(JSON, default=dict)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

class MCPToolConfig(Base):
    """Per-tenant MCP tool config.

    This is the EXACT bug TenantLLMConfig above documents as fixed for model
    keys - the twin never got the fix. `tool_id` was GLOBALLY unique and
    `api_key` was PLAINTEXT, served from a GET with no tenant scope at all, so
    every tenant could read and overwrite every other tenant's tool credentials.

    Now: unique per (tenant_id, tool_id), Fernet-encrypted at rest, never
    serialized back out. The plaintext column was DROPPED rather than migrated:
    any key that lived in it was readable by every tenant and must be treated as
    compromised and rotated, not carried forward.
    """
    __tablename__ = 'config_mcp_tools'
    __table_args__ = (
        UniqueConstraint('tenant_id', 'tool_id', name='uq_mcp_tenant_tool'),
    )
    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    tool_id = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)
    rate_limit_per_hour = Column(Integer, default=1000)
    api_key_encrypted = Column(String, nullable=True)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

class OntologyConfig(Base):
    """Per-tenant ontology tuning. `department` was globally unique: one tenant's
    row was the only row that could exist for that department, and writes keyed
    on it alone mutated whichever tenant got there first."""
    __tablename__ = 'config_ontology'
    __table_args__ = (
        UniqueConstraint('tenant_id', 'department', name='uq_ontology_tenant_dept'),
    )
    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    department = Column(String, nullable=False)
    default_half_life_days = Column(Integer, default=90)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

class FederatedConfig(Base):
    """Per-tenant federated-sharing opt-in. `department` was globally unique, so
    one tenant could flip another tenant's PRIVACY CONSENT for data sharing."""
    __tablename__ = 'config_federated'
    __table_args__ = (
        UniqueConstraint('tenant_id', 'department', name='uq_federated_tenant_dept'),
    )
    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    department = Column(String, nullable=False)
    opt_in = Column(Boolean, default=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
