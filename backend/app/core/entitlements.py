"""
Plan -> entitlements map + require_entitlement() FastAPI dependency (theme M).

Open-core stays open: when KAEOS_MANAGED_CLOUD is false (the default, i.e. every
self-host install) require_entitlement is a NO-OP and every feature is reachable.
Only in managed cloud does Tenant.plan gate the managed/enterprise surfaces
(SSO, SCIM, webhooks, advanced connectors).

Tenant.plan was previously written-once-never-read; this is the reader.
"""
from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.tenant import get_tenant

# Feature slugs gated in managed cloud. Keep in sync with the routes that gate.
FEATURES = frozenset({"webhooks", "sso", "scim", "advanced_connectors"})

# Plan -> features included. Unknown/legacy plans fall through to the most
# restrictive tier (free) so a managed surface is never reachable by accident.
PLAN_FEATURES: dict[str, frozenset] = {
    "free": frozenset(),
    "oss": frozenset(),
    "team": frozenset({"webhooks"}),
    "business": frozenset({"webhooks", "sso", "advanced_connectors"}),
    "enterprise": FEATURES,
}

# Included governed executions (gate-pipeline runs) per month, then overage.
PLAN_ALLOWANCE: dict[str, int] = {
    "free": 500,
    "oss": 0,
    "team": 5_000,
    "business": 25_000,
    "enterprise": 100_000,
}


def _managed_cloud() -> bool:
    from app.core.config import get_settings
    return bool(getattr(get_settings(), "KAEOS_MANAGED_CLOUD", False))


def normalize_plan(plan: str | None) -> str:
    p = (plan or "").strip().lower()
    return p if p in PLAN_FEATURES else "free"


def entitlements_for_plan(plan: str | None) -> frozenset:
    return PLAN_FEATURES[normalize_plan(plan)]


def allowance_for_plan(plan: str | None) -> int:
    return PLAN_ALLOWANCE[normalize_plan(plan)]


async def plan_for_tenant(db: AsyncSession, tenant_id: str) -> str:
    """Tenant.plan, or 'free' if the tenant has no registry row."""
    from app.models.auth import Tenant
    plan = await db.scalar(select(Tenant.plan).where(Tenant.tenant_id == tenant_id))
    return plan or "free"


def require_entitlement(feature: str):
    """FastAPI Depends() factory gating a managed feature behind the tenant plan.

    No-op for self-host (KAEOS_MANAGED_CLOUD unset). In managed cloud, reads
    Tenant.plan and 402s if the feature is not included.
    """
    async def _checker(
        tenant: dict = Depends(get_tenant),
        db: AsyncSession = Depends(get_db),
    ) -> dict:
        if not _managed_cloud():
            return tenant
        plan = await plan_for_tenant(db, tenant["tenant_id"])
        if feature not in entitlements_for_plan(plan):
            raise HTTPException(
                status_code=402,
                detail=(
                    f"The '{feature}' feature is not included in your '{plan}' plan. "
                    f"Upgrade to unlock it."
                ),
            )
        return tenant

    return _checker
