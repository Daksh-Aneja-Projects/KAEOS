from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import List

from app.core.database import get_db
from app.models.settings import TenantLLMConfig, MCPToolConfig, OntologyConfig, FederatedConfig
from app.core.tenant import get_tenant_id, require_role
from app.core.audit import record_security_event

router = APIRouter(prefix="/config", tags=["Platform Config"])

# -- LLM Routing & BYOK --
VALID_LAYERS = {"TIER_1_COMPLEX", "TIER_2_STANDARD", "TIER_3_FAST", "TIER_EMBEDDING"}
# Providers that never require an API key — a stored key for one is meaningless.
_KEYLESS_PROVIDERS = {"ollama"}


class LLMConfigIn(BaseModel):
    layer: str
    model_name: str
    provider: str
    api_key: str | None = None   # write-only; encrypted at rest, never returned
    api_base: str | None = None


class LLMConfigOut(BaseModel):
    """Response shape — deliberately has no api_key field."""
    id: str
    layer: str
    model_name: str
    provider: str
    api_base: str | None = None
    key_configured: bool = False
    capability_profile: dict = {}


def _to_out(row: TenantLLMConfig) -> LLMConfigOut:
    return LLMConfigOut(
        id=row.id,
        layer=row.layer,
        model_name=row.model_name,
        provider=row.provider,
        api_base=row.api_base,
        key_configured=bool(row.api_key_encrypted),
        capability_profile=row.capability_profile or {},
    )


@router.get("/llm-routing", response_model=List[LLMConfigOut])
async def get_llm_routing(
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Tenant-scoped model routing. Secrets are never serialized."""
    res = await db.execute(
        select(TenantLLMConfig).where(TenantLLMConfig.tenant_id == tenant_id)
    )
    return [_to_out(r) for r in res.scalars().all()]


@router.post("/llm-routing", response_model=LLMConfigOut)
async def update_llm_routing(
    item: LLMConfigIn,
    tenant: dict = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Upsert this tenant's model for a tier. The key is encrypted at rest."""
    from app.services.live_connectors import encrypt_secrets

    tenant_id = tenant["tenant_id"]
    if item.layer not in VALID_LAYERS:
        raise HTTPException(400, detail=f"layer must be one of {sorted(VALID_LAYERS)}")

    res = await db.execute(
        select(TenantLLMConfig).where(
            TenantLLMConfig.tenant_id == tenant_id,
            TenantLLMConfig.layer == item.layer,
        )
    )
    db_item = res.scalar_one_or_none()
    if not db_item:
        db_item = TenantLLMConfig(tenant_id=tenant_id, layer=item.layer)
        db.add(db_item)

    model_changed = db_item.model_name != item.model_name
    provider_changed = db_item.provider != item.provider
    db_item.model_name = item.model_name
    db_item.provider = item.provider
    db_item.api_base = item.api_base
    if item.api_key:
        db_item.api_key_encrypted = encrypt_secrets({"api_key": item.api_key})
    elif (item.provider or "").lower() in _KEYLESS_PROVIDERS or provider_changed:
        # A keyless provider (Ollama) must never carry a key, and a key stored
        # for a DIFFERENT provider is meaningless — and, if it was written under
        # an old SECRET_KEY, undecryptable. Clear it rather than leaving a stale
        # blob that later fails the probe with a cryptic decrypt error.
        db_item.api_key_encrypted = None
    # A new model invalidates the old capability profile — force a re-probe.
    if model_changed:
        db_item.capability_profile = {}

    await db.commit()
    await db.refresh(db_item)
    await record_security_event(
        tenant_id=tenant_id, event_type="CONFIG_CHANGE", action="WRITE",
        actor=tenant.get("name"), actor_role=tenant.get("role"),
        resource_type="llm_routing", resource_id=item.layer,
    )
    return _to_out(db_item)


@router.delete("/llm-routing/{layer}")
async def delete_llm_routing(
    layer: str,
    tenant: dict = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Remove a tenant's override for a tier, falling back to platform defaults."""
    tenant_id = tenant["tenant_id"]
    res = await db.execute(
        select(TenantLLMConfig).where(
            TenantLLMConfig.tenant_id == tenant_id,
            TenantLLMConfig.layer == layer,
        )
    )
    db_item = res.scalar_one_or_none()
    if not db_item:
        raise HTTPException(404, detail="No configuration for that layer")
    await db.delete(db_item)
    await db.commit()
    await record_security_event(
        tenant_id=tenant_id, event_type="CONFIG_CHANGE", action="DELETE",
        actor=tenant.get("name"), actor_role=tenant.get("role"),
        resource_type="llm_routing", resource_id=layer,
    )
    return {"status": "deleted", "layer": layer}


@router.post("/llm-routing/{layer}/probe")
async def probe_llm_model(
    layer: str,
    tenant: dict = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """
    Self-calibrate against the tenant's configured model and persist the
    capability profile. The resulting tier_ceiling caps how much autonomy the
    gates will grant this model — a weaker model routes more work to humans.
    """
    from app.services.live_connectors import decrypt_secrets
    from app.services.model_probe import model_probe

    tenant_id = tenant["tenant_id"]
    res = await db.execute(
        select(TenantLLMConfig).where(
            TenantLLMConfig.tenant_id == tenant_id,
            TenantLLMConfig.layer == layer,
        )
    )
    cfg = res.scalar_one_or_none()
    if not cfg:
        raise HTTPException(404, detail="No configuration for that layer")

    api_key = None
    if cfg.api_key_encrypted:
        try:
            api_key = decrypt_secrets(cfg.api_key_encrypted).get("api_key")
        except ValueError as e:
            # A keyless provider (Ollama) doesn't need the key at all — a stale,
            # undecryptable blob must not block its probe. Providers that DO
            # require a key still fail loudly.
            if (cfg.provider or "").lower() in _KEYLESS_PROVIDERS:
                import logging
                logging.getLogger(__name__).warning(
                    f"[Probe] ignoring undecryptable key for keyless provider "
                    f"{cfg.provider} on layer {layer}"
                )
            else:
                raise HTTPException(400, detail=str(e))

    profile = await model_probe.run(
        model_name=cfg.model_name,
        api_key=api_key,
        provider=cfg.provider,
        api_base=cfg.api_base,
    )
    cfg.capability_profile = profile
    await db.commit()
    await record_security_event(
        tenant_id=tenant_id, event_type="CONFIG_CHANGE", action="WRITE",
        actor=tenant.get("name"), actor_role=tenant.get("role"),
        resource_type="llm_routing_probe", resource_id=layer,
    )
    return {"layer": layer, "model_name": cfg.model_name, "profile": profile}

# -- MCP Tools --
#
# Every query below is tenant-scoped and the key is write-only. Previously the
# GET had no tenant dependency AT ALL and returned api_key in plaintext for
# every tenant, and the POST looked the row up by a globally-unique tool_id -
# so writing your own config silently overwrote another tenant's credentials.

class MCPToolIn(BaseModel):
    tool_id: str
    is_active: bool
    rate_limit_per_hour: int
    api_key: str | None = None   # write-only; encrypted at rest, never returned


class MCPToolOut(BaseModel):
    """Response shape — deliberately has no api_key field."""
    id: str
    tool_id: str
    is_active: bool
    rate_limit_per_hour: int
    key_configured: bool = False


def _mcp_to_out(row: MCPToolConfig) -> MCPToolOut:
    return MCPToolOut(
        id=row.id,
        tool_id=row.tool_id,
        is_active=row.is_active,
        rate_limit_per_hour=row.rate_limit_per_hour,
        key_configured=bool(row.api_key_encrypted),
    )


@router.get("/mcp-tools", response_model=List[MCPToolOut])
async def get_mcp_tools(
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """This tenant's MCP tools. Secrets are never serialized."""
    res = await db.execute(
        select(MCPToolConfig).where(MCPToolConfig.tenant_id == tenant_id)
    )
    return [_mcp_to_out(r) for r in res.scalars().all()]


@router.post("/mcp-tools", response_model=MCPToolOut)
async def update_mcp_tool(
    item: MCPToolIn,
    tenant: dict = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Upsert THIS tenant's config for a tool. The key is encrypted at rest."""
    from app.services.live_connectors import encrypt_secrets

    tenant_id = tenant["tenant_id"]
    res = await db.execute(
        select(MCPToolConfig).where(
            MCPToolConfig.tenant_id == tenant_id,
            MCPToolConfig.tool_id == item.tool_id,
        )
    )
    db_item = res.scalar_one_or_none()
    if not db_item:
        db_item = MCPToolConfig(tenant_id=tenant_id, tool_id=item.tool_id)
        db.add(db_item)

    db_item.is_active = item.is_active
    db_item.rate_limit_per_hour = item.rate_limit_per_hour
    # Blank means "leave the stored key alone" — otherwise editing a rate limit
    # would silently wipe the credential.
    if item.api_key:
        db_item.api_key_encrypted = encrypt_secrets({"api_key": item.api_key})

    await db.commit()
    await db.refresh(db_item)
    await record_security_event(
        tenant_id=tenant_id, event_type="CONFIG_CHANGE", action="WRITE",
        actor=tenant.get("name"), actor_role=tenant.get("role"),
        resource_type="mcp_tool", resource_id=item.tool_id,
    )
    return _mcp_to_out(db_item)

# -- Ontology --
class OntologyItem(BaseModel):
    id: str | None = None
    department: str
    default_half_life_days: int

@router.get("/ontology", response_model=List[OntologyItem])
async def get_ontology(
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    res = await db.execute(
        select(OntologyConfig).where(OntologyConfig.tenant_id == tenant_id)
    )
    return res.scalars().all()

@router.post("/ontology", response_model=OntologyItem)
async def update_ontology(item: OntologyItem, tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db)):
    # Scoped to (tenant, department): `department` alone was globally unique, so
    # this write landed on whichever tenant's row existed.
    tenant_id = tenant["tenant_id"]
    res = await db.execute(
        select(OntologyConfig).where(
            OntologyConfig.tenant_id == tenant_id,
            OntologyConfig.department == item.department,
        )
    )
    db_item = res.scalar_one_or_none()
    if db_item:
        db_item.default_half_life_days = item.default_half_life_days
    else:
        db_item = OntologyConfig(
            tenant_id=tenant_id,
            department=item.department,
            default_half_life_days=item.default_half_life_days
        )
        db.add(db_item)
    await db.commit()
    await db.refresh(db_item)
    await record_security_event(
        tenant_id=tenant_id, event_type="CONFIG_CHANGE", action="WRITE",
        actor=tenant.get("name"), actor_role=tenant.get("role"),
        resource_type="ontology", resource_id=item.department,
    )
    return db_item

# -- Federated --
class FederatedItem(BaseModel):
    id: str | None = None
    department: str
    opt_in: bool

@router.get("/federated", response_model=List[FederatedItem])
async def get_federated(
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    res = await db.execute(
        select(FederatedConfig).where(FederatedConfig.tenant_id == tenant_id)
    )
    return res.scalars().all()

@router.post("/federated", response_model=FederatedItem)
async def update_federated(item: FederatedItem, tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db)):
    # Scoped to (tenant, department). This flips a PRIVACY CONSENT flag for
    # federated data sharing; keyed on `department` alone it flipped whichever
    # tenant's row existed first.
    tenant_id = tenant["tenant_id"]
    res = await db.execute(
        select(FederatedConfig).where(
            FederatedConfig.tenant_id == tenant_id,
            FederatedConfig.department == item.department,
        )
    )
    db_item = res.scalar_one_or_none()
    if db_item:
        db_item.opt_in = item.opt_in
    else:
        db_item = FederatedConfig(
            tenant_id=tenant_id,
            department=item.department,
            opt_in=item.opt_in
        )
        db.add(db_item)
    await db.commit()
    await db.refresh(db_item)
    await record_security_event(
        tenant_id=tenant_id, event_type="CONFIG_CHANGE", action="WRITE",
        actor=tenant.get("name"), actor_role=tenant.get("role"),
        resource_type="federated_consent", resource_id=item.department,
    )
    return db_item


# ── Autonomy Dial (per-domain risk appetite) ─────────────────────────────────
_AUTONOMY_DOMAINS = ["hr", "finance", "legal", "sales", "support", "operations", "engineering"]


class AutonomyItem(BaseModel):
    domain: str
    min_confidence: float
    is_default: bool


class AutonomyUpdate(BaseModel):
    min_confidence: float


@router.get("/autonomy", response_model=List[AutonomyItem])
async def get_autonomy(
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Per-domain autonomy thresholds (the Autonomy Dial). Domains without an
    explicit policy fall back to the platform default confidence threshold."""
    from app.models.settings import AutonomyPolicy
    from app.core.config import get_settings
    default = get_settings().CONFIDENCE_AUTONOMOUS_EXEC
    rows = (await db.execute(
        select(AutonomyPolicy).where(AutonomyPolicy.tenant_id == tenant_id)
    )).scalars().all()
    by_domain = {r.domain: r.min_confidence for r in rows}
    return [
        AutonomyItem(domain=d, min_confidence=by_domain.get(d, default), is_default=d not in by_domain)
        for d in _AUTONOMY_DOMAINS
    ]


@router.put("/autonomy/{domain}", response_model=AutonomyItem)
async def set_autonomy(
    domain: str,
    body: AutonomyUpdate,
    tenant: dict = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Set a domain's autonomy threshold (admin only). Higher = more human
    oversight, lower = more autonomy. Clamped to [0.5, 0.99]."""
    from app.models.settings import AutonomyPolicy
    d = domain.strip().lower()
    if d not in _AUTONOMY_DOMAINS:
        raise HTTPException(status_code=400, detail=f"Unknown domain '{domain}'")
    val = max(0.5, min(0.99, float(body.min_confidence)))
    tenant_id = tenant["tenant_id"]
    existing = (await db.execute(
        select(AutonomyPolicy).where(
            AutonomyPolicy.tenant_id == tenant_id, AutonomyPolicy.domain == d)
    )).scalar_one_or_none()
    if existing:
        existing.min_confidence = val
    else:
        db.add(AutonomyPolicy(tenant_id=tenant_id, domain=d, min_confidence=val))
    await db.commit()
    # Invalidate the runtime cache so the dial takes effect promptly.
    try:
        from app.services.autonomy_policy import invalidate as _inv
        _inv(tenant_id, d)
    except Exception:
        pass
    await record_security_event(
        tenant_id=tenant_id, event_type="CONFIG_CHANGE", action="WRITE",
        actor=tenant.get("name"), actor_role=tenant.get("role"),
        resource_type="autonomy_policy", resource_id=d, details={"min_confidence": val},
    )
    return AutonomyItem(domain=d, min_confidence=val, is_default=False)
