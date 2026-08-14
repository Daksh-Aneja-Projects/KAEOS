"""KAEOS — Super-admin OPERATOR CONSOLE (/ops) + public STATUS (/status).

The operator console is CROSS-TENANT by design: it enumerates every tenant and
their usage/health so a platform operator can run the fleet. That is exactly the
read a customer JWT must NOT authorize, so every /ops route is gated by
``require_superadmin`` (the ADMIN_SECRET gate, reused - see app/core/admin.py)
and reads through the OWNER/maintenance session (RLS-bypassing by design, the
same necessary carve-out email->tenant login and api-key lookup already use).

/status is the opposite: PUBLIC, unauthenticated, read-only, and must never leak
per-tenant data. It reports process liveness, dependency reachability, and the
platform-wide BLENDED safe-autonomy rate (one aggregate number, no tenant split).
"""
import time

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import func, select

from app.core.admin import require_superadmin
from app.core.database import MaintenanceSessionLocal
from app.models.auth import Tenant

# Process start — uptime is measured from when this module is imported, which is
# app boot (main.py imports it during router wiring). Good enough for a status
# page; not a substitute for real orchestrator uptime.
_STARTED = time.monotonic()

# Every /ops route is super-admin only. Declared on the router so a new route
# cannot accidentally ship ungated.
router = APIRouter(prefix="/ops", tags=["Operator Console"],
                   dependencies=[Depends(require_superadmin)])

# /status is app-root, public, no prefix — mounted like /health.
status_router = APIRouter(tags=["Status"])


async def _blended_safe_autonomy(db, days: int = 30) -> float | None:
    """Platform-wide safe-autonomy rate across ALL tenants (owner session).

    Reuses the same clean/autonomous classification as the per-tenant metric
    (app.services.safe_autonomy._classify_counts) so the blended number means
    exactly what the per-tenant one does — just without the tenant filter.
    Honesty contract: no executions in window -> None, never a fabricated 0.
    """
    from datetime import datetime, timedelta, timezone

    from app.models.domain import SkillExecution
    from app.services.safe_autonomy import _classify_counts

    since = datetime.now(timezone.utc) - timedelta(days=days)
    autonomous_safe, *_ = _classify_counts()
    row = (await db.execute(
        select(func.count().label("total"), autonomous_safe.label("safe"))
        .where(SkillExecution.started_at >= since)
    )).one()
    total = int(row.total or 0)
    if not total:
        return None
    return round(int(row.safe or 0) / total, 4)


@router.get("/tenants")
async def list_tenants():
    """Every tenant with plan/status and light per-tenant counts (owner session).

    Cross-tenant and RLS-bypassing BY DESIGN — super-admin only (see module
    docstring). Counts are cheap fleet-overview aggregates, not full usage.
    """
    from app.models.agent_factory import DeployedAgent
    from app.models.domain import SkillExecution

    async with MaintenanceSessionLocal() as db:
        tenants = (await db.execute(
            select(Tenant).order_by(Tenant.created_at.asc())
        )).scalars().all()

        agent_counts = dict((await db.execute(
            select(DeployedAgent.tenant_id, func.count(DeployedAgent.id))
            .group_by(DeployedAgent.tenant_id)
        )).all())
        exec_counts = dict((await db.execute(
            select(SkillExecution.tenant_id, func.count(SkillExecution.id))
            .group_by(SkillExecution.tenant_id)
        )).all())

    return {
        "count": len(tenants),
        "tenants": [
            {
                "id": t.tenant_id,
                "name": t.name,
                "plan": t.plan,
                "is_active": t.is_active,
                "created_at": t.created_at.isoformat() if t.created_at else None,
                "agent_count": int(agent_counts.get(t.tenant_id, 0)),
                "execution_count": int(exec_counts.get(t.tenant_id, 0)),
            }
            for t in tenants
        ],
    }


@router.get("/tenants/{tenant_id}")
async def tenant_detail(tenant_id: str):
    """One tenant's usage (billing rating), plan/entitlements, and health.

    Owner session; super-admin only. Reuses rate_tenant_period (usage_rating),
    entitlements_for_plan (entitlements), and compute_safe_autonomy — no forked
    logic. 404 for an unknown tenant so a caller cannot probe existence blindly.
    """
    from app.core.entitlements import entitlements_for_plan
    from app.models.agent_factory import DeployedAgent
    from app.models.domain import SkillExecution
    from app.services.safe_autonomy import compute_safe_autonomy
    from app.services.usage_rating import rate_tenant_period

    async with MaintenanceSessionLocal() as db:
        t = (await db.execute(
            select(Tenant).where(Tenant.tenant_id == tenant_id)
        )).scalar_one_or_none()
        if t is None:
            raise HTTPException(404, "Tenant not found")

        usage = await rate_tenant_period(db, tenant_id)
        sar = await compute_safe_autonomy(db, tenant_id, days=30)
        agent_count = await db.scalar(
            select(func.count(DeployedAgent.id)).where(DeployedAgent.tenant_id == tenant_id)
        ) or 0
        exec_count = await db.scalar(
            select(func.count(SkillExecution.id)).where(SkillExecution.tenant_id == tenant_id)
        ) or 0

    return {
        "id": t.tenant_id,
        "name": t.name,
        "plan": t.plan,
        "is_active": t.is_active,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "entitlements": sorted(entitlements_for_plan(t.plan)),
        "usage": usage,
        "health": {
            "agent_count": int(agent_count),
            "execution_count": int(exec_count),
            "safe_autonomy_rate": sar.get("safe_autonomy_rate"),
        },
    }


@router.get("/overview")
async def overview():
    """Platform totals: tenant counts, execution volume, blended safe-autonomy,
    plan distribution. Owner session; super-admin only.

    Honesty contract: blended safe-autonomy is null (not 0) when no executions
    exist in the window.
    """
    from app.models.domain import SkillExecution

    async with MaintenanceSessionLocal() as db:
        total_tenants = await db.scalar(select(func.count(Tenant.tenant_id))) or 0
        active_tenants = await db.scalar(
            select(func.count(Tenant.tenant_id)).where(Tenant.is_active == True)  # noqa: E712
        ) or 0
        total_executions = await db.scalar(select(func.count(SkillExecution.id))) or 0
        plan_rows = (await db.execute(
            select(Tenant.plan, func.count(Tenant.tenant_id)).group_by(Tenant.plan)
        )).all()
        blended = await _blended_safe_autonomy(db, days=30)

    return {
        "tenant_count": int(total_tenants),
        "active_tenants": int(active_tenants),
        "total_executions": int(total_executions),
        "blended_safe_autonomy_rate": blended,
        "plan_distribution": {p or "unknown": int(c) for p, c in plan_rows},
        "note": (None if blended is not None else
                 "No executions in the last 30 days; blended rate is null, not a "
                 "fabricated 0."),
    }


@status_router.get("/status")
async def status(response: Response):
    """PUBLIC status page — no auth, no per-tenant data.

    Reuses main._probe_dependencies() (redis/llm reachability) rather than
    forking it; adds a DB ping. Returns 503 when the database (the only critical
    dependency) is unreachable, so load balancers can act on it.
    """
    from sqlalchemy import text

    from app.core.config import get_settings
    from app.main import _probe_dependencies

    settings = get_settings()

    db_ok = True
    try:
        async with MaintenanceSessionLocal() as db:
            await db.execute(text("SELECT 1"))
    except Exception:
        db_ok = False

    deps = await _probe_dependencies()
    dependencies = {
        "db": db_ok,
        "redis": bool(deps.get("redis", {}).get("available")),
        "llm": bool(deps.get("llm", {}).get("available")),
    }

    if not db_ok:
        response.status_code = 503

    # NOTE: platform safe-autonomy rate is deliberately NOT exposed here. It is a
    # business metric, and its cross-tenant aggregate is an unindexed full scan
    # (skill_executions is indexed tenant_id-leading) - a DoS amplifier on an
    # auth-free endpoint. It lives on the super-admin-gated /ops/overview instead.
    return {
        "status": "ok" if db_ok else "degraded",
        "version": settings.APP_VERSION,
        "uptime_seconds": round(time.monotonic() - _STARTED, 1),
        "dependencies": dependencies,
    }
