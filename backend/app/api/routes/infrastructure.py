"""
KAEOS S1 — Infrastructure Layer API Routes
N1: Model Management, N2: Cost Governor, N3: Agent Protocol, N4: Onboarding
"""
from typing import Optional
from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin import is_admin, verify_admin_secret
from app.core.database import MaintenanceSessionLocal, get_db
from app.core.tenant import get_tenant_id, require_role
from app.services.model_management import ModelManagementService
from app.services.cost_governor import CostGovernorService
from app.services.agent_protocol import AgentProtocolService
from app.services.onboarding_engine import OnboardingEngineService

router = APIRouter(tags=["Infrastructure (S1)"])


# ── N1: Model Management ─────────────────────────────────────────────────────

@router.get("/infrastructure/models")
async def list_models(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    """N1 — List all registered LLM models with performance benchmarks."""
    return await ModelManagementService.get_registry(db, tenant_id)


@router.post("/infrastructure/models")
async def register_model(data: dict, tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db)):
    """N1 — Register a new model in the 4-tier catalog. Requires operator role."""
    tenant_id = tenant["tenant_id"]
    from app.models.infrastructure import ModelTier
    tier_map = {"FAST": ModelTier.FAST, "STANDARD": ModelTier.STANDARD,
                "DEEP": ModelTier.DEEP, "VERTICAL": ModelTier.VERTICAL}
    return await ModelManagementService.register_model(
        db, tenant_id,
        model_name=data.get("model_name", ""),
        provider=data.get("provider", "anthropic"),
        tier=tier_map.get(data.get("tier", "STANDARD"), ModelTier.STANDARD),
        cost_per_1k_input=data.get("cost_per_1k_input", 0.0),
        cost_per_1k_output=data.get("cost_per_1k_output", 0.0),
        max_context_window=data.get("max_context_window", 200000),
        use_cases=data.get("use_cases", []),
        is_canary=data.get("is_canary", False)
    )


@router.post("/infrastructure/models/route")
async def route_model(data: dict, tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    """N1 — Route a request to the best model for the given task type."""
    return await ModelManagementService.route_to_model(
        db, tenant_id,
        request_type=data.get("request_type", ""),
        preferred_tier=None
    )


@router.get("/infrastructure/prompts")
async def list_prompts(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    """N1 — List all active prompt templates."""
    return await ModelManagementService.list_prompts(db, tenant_id)


@router.post("/infrastructure/prompts")
async def register_prompt(data: dict, tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db)):
    """N1 — Register a versioned prompt template. Requires operator role."""
    tenant_id = tenant["tenant_id"]
    return await ModelManagementService.register_prompt(
        db, tenant_id,
        template_key=data.get("template_key", ""),
        system_prompt=data.get("system_prompt", ""),
        user_template=data.get("user_template"),
        max_tokens=data.get("max_tokens", 4096),
        temperature=data.get("temperature", 0.7)
    )


@router.get("/infrastructure/models/estimate")
async def estimate_tokens(request_type: str = Query("extraction")):
    """N1 — Pre-compute expected token usage per workflow type."""
    return await ModelManagementService.estimate_token_budget(request_type)


# ── N2: Cost Governor ─────────────────────────────────────────────────────────

@router.get("/infrastructure/cost/telemetry")
async def get_cost_telemetry(hours: int = Query(24), tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    """N2 — Real-time cost telemetry: token consumption per model, agent, workflow."""
    return await CostGovernorService.get_cost_telemetry(db, tenant_id, hours)


@router.get("/infrastructure/cost/budgets")
async def list_budgets(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    """N2 — List all token budget allocations."""
    return await CostGovernorService.get_budgets(db, tenant_id)


@router.post("/infrastructure/cost/budgets")
async def create_budget(data: dict, tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db)):
    """N2 — Create or update a token budget allocation. Requires operator role."""
    tenant_id = tenant["tenant_id"]
    return await CostGovernorService.create_budget(
        db, tenant_id,
        scope=data.get("scope", "tenant"),
        scope_id=data.get("scope_id"),
        token_limit=data.get("token_limit", 10_000_000),
        cost_limit_usd=data.get("cost_limit_usd", 100.0)
    )


@router.post("/infrastructure/cost/check")
async def check_budget(data: dict, tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    """N2 — Check if a request is within budget."""
    return await CostGovernorService.check_budget(
        db, tenant_id,
        estimated_tokens=data.get("estimated_tokens", 0),
        scope=data.get("scope", "tenant")
    )


@router.post("/infrastructure/cost/record")
async def record_usage(data: dict, tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    """N2 — Record token consumption event."""
    return await CostGovernorService.record_usage(
        db, tenant_id,
        model_name=data.get("model_name", ""),
        model_tier=data.get("model_tier", "STANDARD"),
        input_tokens=data.get("input_tokens", 0),
        output_tokens=data.get("output_tokens", 0),
        cost_usd=data.get("cost_usd", 0.0),
        latency_ms=data.get("latency_ms", 0),
        agent_id=data.get("agent_id"),
        request_type=data.get("request_type")
    )


# ── N3: Agent Protocol ────────────────────────────────────────────────────────

@router.get("/infrastructure/agents/registry")
async def list_agent_registry(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    """N3 — List all registered agents with capabilities and health status."""
    return await AgentProtocolService.list_agents(db, tenant_id)


@router.post("/infrastructure/agents/register")
async def register_agent(data: dict, tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db)):
    """N3 — Register an agent in the discovery registry. Requires operator role."""
    tenant_id = tenant["tenant_id"]
    return await AgentProtocolService.register_agent(
        db, tenant_id,
        agent_name=data.get("agent_name", ""),
        agent_type=data.get("agent_type", "base"),
        capabilities=data.get("capabilities", []),
        max_concurrent=data.get("max_concurrent", 10)
    )


@router.post("/infrastructure/agents/discover")
async def discover_agent(data: dict, tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    """N3 — Find the best available agent for a given capability."""
    result = await AgentProtocolService.discover_agent(
        db, tenant_id, capability=data.get("capability", "")
    )
    return result or {"error": "no_matching_agent_found"}


@router.post("/infrastructure/agents/message")
async def send_agent_message(data: dict, tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    """N3 — Send an async message between agents."""
    return await AgentProtocolService.send_message(
        db, tenant_id,
        sender_agent_id=data.get("sender_agent_id", ""),
        receiver_agent_id=data.get("receiver_agent_id", ""),
        message_type=data.get("message_type", "request"),
        payload=data.get("payload", {}),
        context_envelope=data.get("context_envelope"),
        correlation_id=data.get("correlation_id"),
        priority=data.get("priority", 5)
    )


@router.get("/infrastructure/agents/messages")
async def get_messages(
    correlation_id: str = Query(None),
    limit: int = Query(50),
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db)
):
    """N3 — Get message history."""
    return await AgentProtocolService.get_message_history(
        db, tenant_id, correlation_id=correlation_id, limit=limit
    )


@router.post("/infrastructure/agents/{agent_name}/heartbeat")
async def agent_heartbeat(agent_name: str, data: Optional[dict] = None, tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    """N3 — Update agent heartbeat and load."""
    data = data or {}   # a mutable default is shared across every request
    await AgentProtocolService.heartbeat(
        db, tenant_id, agent_name, current_load=data.get("current_load", 0)
    )
    return {"status": "ok"}


@router.post("/infrastructure/agents/{agent_name}/circuit/reset")
async def reset_circuit(agent_name: str, tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    """N3 — Reset circuit breaker for an agent."""
    await AgentProtocolService.reset_circuit(db, tenant_id, agent_name)
    return {"status": "circuit_reset", "agent_name": agent_name}


# ── N4: Tenant Onboarding ─────────────────────────────────────────────────────

# ── Tenant provisioning is CROSS-TENANT by nature, so it is admin-gated ──────
#
# These four endpoints took a tenant_id from the request body or the URL path
# and never checked it against the caller. Any tenant could read, advance, or
# enumerate any other tenant's onboarding. Postgres RLS now blocks the data
# leak at the database, but an endpoint that relies on RLS to be safe is still
# wrong: it is broken-by-design on SQLite dev, and "create a tenant that isn't
# you" legitimately CANNOT work under RLS (the WITH CHECK fails), which is how
# this surfaced - as a 500.
#
# Rule: you may always act on YOUR OWN tenant. Acting on another tenant - or on
# all of them - is a platform operation and needs X-Admin-Secret. Admin-scoped
# work runs on the OWNER session, which is RLS-exempt by design.

@router.get("/infrastructure/onboarding")
async def list_onboardings(
    tenant_id: str = Depends(get_tenant_id),
    x_admin_secret: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db),
):
    """N4 — Onboarding records for the caller's tenant.

    A platform admin (valid X-Admin-Secret) gets every tenant's record; without
    one this returned ALL tenants' rows to ANY caller.
    """
    if is_admin(x_admin_secret):
        async with MaintenanceSessionLocal() as owner_db:
            return await OnboardingEngineService.list_all_onboardings(owner_db)
    return await OnboardingEngineService.list_onboardings_for_tenant(db, tenant_id)


@router.get("/infrastructure/onboarding/{tenant_id}")
async def get_onboarding(
    tenant_id: str,
    caller_tenant: str = Depends(get_tenant_id),
    x_admin_secret: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db),
):
    """N4 — Onboarding status for a tenant (your own, or any with admin)."""
    if tenant_id != caller_tenant:
        verify_admin_secret(x_admin_secret)
        async with MaintenanceSessionLocal() as owner_db:
            result = await OnboardingEngineService.get_onboarding_status(owner_db, tenant_id)
            return result or {"error": "not_found"}
    result = await OnboardingEngineService.get_onboarding_status(db, tenant_id)
    return result or {"error": "not_found"}


@router.post("/infrastructure/onboarding")
async def initiate_onboarding(
    data: dict,
    tenant_id: str = Depends(get_tenant_id),
    x_admin_secret: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db),
):
    """N4 — Start onboarding for a tenant.

    Provisioning a tenant OTHER than your own is a platform action: it needs
    X-Admin-Secret and runs on the owner session, because RLS correctly refuses
    to let one tenant insert a row belonging to another.
    """
    target = data.get("tenant_id", tenant_id)
    name = data.get("tenant_name", "Default Tenant")
    vertical = data.get("industry_vertical")

    if target != tenant_id:
        verify_admin_secret(x_admin_secret)
        async with MaintenanceSessionLocal() as owner_db:
            return await OnboardingEngineService.initiate_onboarding(
                owner_db, tenant_id=target, tenant_name=name, industry_vertical=vertical
            )
    return await OnboardingEngineService.initiate_onboarding(
        db, tenant_id=target, tenant_name=name, industry_vertical=vertical
    )


@router.post("/infrastructure/onboarding/{tenant_id}/advance")
async def advance_onboarding(
    tenant_id: str,
    data: Optional[dict] = None,
    caller_tenant: str = Depends(get_tenant_id),
    x_admin_secret: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db),
):
    """N4 — Advance a tenant's onboarding stage (your own, or any with admin)."""
    data = data or {}   # a mutable default is shared across every request
    if tenant_id != caller_tenant:
        verify_admin_secret(x_admin_secret)
        async with MaintenanceSessionLocal() as owner_db:
            return await OnboardingEngineService.advance_stage(
                owner_db, tenant_id, metrics=data.get("metrics")
            )
    return await OnboardingEngineService.advance_stage(db, tenant_id, metrics=data.get("metrics"))


@router.post("/infrastructure/onboarding/{tenant_id}/bootstrap-admin")
async def bootstrap_tenant_admin(
    tenant_id: str,
    data: dict,
    x_admin_secret: Optional[str] = Header(None),
):
    """N4 — Create the FIRST admin login for a freshly-provisioned tenant.

    This is the one onboarding step tenant-scoped `/auth/users` cannot perform:
    it creates a user in a tenant OTHER than the caller's, so — like tenant
    provisioning — it is a platform operation gated on X-Admin-Secret and run on
    the RLS-exempt owner session.

    Deliberately a BOOTSTRAP, not a general create: it refuses if the tenant
    already has any user. Subsequent users are added by that tenant's own admin
    through `/auth/users`, which keeps every later user creation inside the
    tenant boundary. `users` is a GLOBAL_TABLES row (RLS-exempt for login), so
    the caller MUST be the platform operator — there is no RLS backstop here.
    """
    from sqlalchemy import select, func
    from fastapi import HTTPException
    from app.models.auth import User, UserRole
    from app.services.auth import AuthService

    verify_admin_secret(x_admin_secret)

    email = (data.get("email") or "").strip().lower()
    display_name = (data.get("display_name") or "").strip()
    password = data.get("password") or ""
    if not email or not password:
        raise HTTPException(status_code=400, detail="email and password are required")
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="password must be at least 8 characters")

    async with MaintenanceSessionLocal() as owner_db:
        existing = await owner_db.execute(
            select(func.count(User.id)).where(User.tenant_id == tenant_id)
        )
        if (existing.scalar() or 0) > 0:
            raise HTTPException(
                status_code=409,
                detail="Tenant already has users; add more via /auth/users as that tenant's admin.",
            )
        result = await AuthService.create_user(
            owner_db,
            email=email,
            display_name=display_name or email.split("@")[0],
            password=password,
            role=UserRole.ADMIN,
            created_by="platform-onboarding",
            tenant_id=tenant_id,
        )
        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])
        result["tenant_id"] = tenant_id
        return result


@router.post("/infrastructure/schema-mappings/propose")
async def propose_schema_mappings(data: dict, tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    """N4 — AI-propose schema mappings for source fields."""
    return await OnboardingEngineService.propose_mappings(
        db, tenant_id,
        connector_id=data.get("connector_id", ""),
        source_fields=data.get("source_fields", [])
    )


@router.get("/infrastructure/schema-mappings")
async def get_schema_mappings(
    connector_id: str = Query(None),
    confirmed_only: bool = Query(False),
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db)
):
    """N4 — Get schema mappings for a tenant."""
    return await OnboardingEngineService.get_mappings(
        db, tenant_id, connector_id=connector_id, confirmed_only=confirmed_only
    )


@router.post("/infrastructure/schema-mappings/{mapping_id}/confirm")
async def confirm_mapping(mapping_id: str, data: dict, db: AsyncSession = Depends(get_db)):
    """N4 — Admin confirms or corrects a schema mapping."""
    return await OnboardingEngineService.confirm_mapping(
        db, mapping_id,
        confirmed_by=data.get("confirmed_by", "admin"),
        target_entity=data.get("target_entity"),
        target_field=data.get("target_field")
    )
