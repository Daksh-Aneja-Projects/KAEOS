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


# ── KAEOS Enterprise features (fusion F0) ──────────────────────────────────
# These are provided by the private kaeos_enterprise package through the seam
# in app.core.extensions, not by this repo. The fence: anything answering
# "can we prove it / can we let go safely / can other vendors' agents use it"
# is Enterprise. Kept in sync with kaeos_enterprise.FEATURES as phases land.
EE_FEATURES = frozenset({
    "proof",            # F1: offline-verifiable action proofs + auditor bundles
    "decision_proof",   # F2: deterministic arbitration arithmetic
    "trust_ledger",     # F3: earned-autonomy calibration + tier ladder
    "rehearsal",        # F4: predicted-diff dry runs before execution
    "gateway",          # F5: governed MCP/A2A gateway for third-party agents
    "outcome_billing",  # F6: outcome-verified billing + invoice proofs
    "evidence_pack",    # F7: procurement / AI-Act evidence pack generator
})

# In managed cloud, Enterprise features additionally require the plan to
# include them. Self-host entitlement is the Enterprise package's own license
# check (private side); if it registered, the deployment is entitled.
PLAN_EE_FEATURES: dict[str, frozenset] = {
    "free": frozenset(),
    "oss": frozenset(),
    "team": frozenset(),
    "business": frozenset(),
    "enterprise": EE_FEATURES,
}


def require_enterprise(feature: str):
    """FastAPI Depends() factory gating a KAEOS Enterprise capability.

    Refusals are professional and human-readable, never a stack trace:
    402 when the Enterprise package is not installed/loaded, and in managed
    cloud additionally 402 when the tenant plan does not include the feature.
    """
    async def _checker(
        tenant: dict = Depends(get_tenant),
        db: AsyncSession = Depends(get_db),
    ) -> dict:
        from app.core.extensions import extensions
        if not extensions.provides(feature):
            raise HTTPException(
                status_code=402,
                detail=(
                    "This is a KAEOS Enterprise capability. The "
                    f"'{feature}' feature is part of KAEOS Enterprise, which "
                    "is not enabled on this deployment. Contact your KAEOS "
                    "administrator to enable it."
                ),
            )
        if _managed_cloud():
            plan = normalize_plan(await plan_for_tenant(db, tenant["tenant_id"]))
            if feature not in PLAN_EE_FEATURES[plan]:
                raise HTTPException(
                    status_code=402,
                    detail=(
                        "This is a KAEOS Enterprise capability. The "
                        f"'{feature}' feature is not included in your "
                        f"'{plan}' plan. Upgrade to the enterprise plan to "
                        "unlock it."
                    ),
                )
        return tenant

    return _checker


# Executions past the included allowance are billed as overage (soft limit), but
# a runaway tenant is hard-capped at this multiple of the allowance to bound
# spend. ponytail: flat multiple, make it per-plan config if a plan needs its own.
ALLOWANCE_HARD_MULTIPLE = 3


def _allowance_verdict(used: int, allowance: int, hard_multiple: int = ALLOWANCE_HARD_MULTIPLE) -> dict:
    """Pure soft/hard classification of period usage against the plan allowance."""
    hard_cap = allowance * hard_multiple if allowance else 0
    return {
        "used": used,
        "allowance": allowance,
        "hard_cap": hard_cap,
        # soft = into billable overage; hard = past the runaway cap.
        "soft_exceeded": allowance > 0 and used >= allowance,
        "hard_exceeded": hard_cap > 0 and used >= hard_cap,
    }


async def execution_allowance_status(db: AsyncSession, tenant_id: str) -> dict:
    """Where the tenant sits against its plan's execution allowance this period.
    Reuses the same rating the metering job and /billing/entitlements read."""
    from app.services.usage_rating import rate_tenant_period
    rating = await rate_tenant_period(db, tenant_id)
    v = _allowance_verdict(rating["metered_executions"], rating["included_allowance"])
    v["plan"] = rating["plan"]
    return v


def require_execution_allowance():
    """FastAPI Depends() gating a governed execution on the plan allowance.

    No-op for self-host (KAEOS_MANAGED_CLOUD unset), byte-identical to before.
    In managed cloud: overage up to the hard cap is allowed (it is billed); past
    the hard cap it fails closed with 429 to stop runaway spend.
    """
    async def _checker(
        tenant: dict = Depends(get_tenant),
        db: AsyncSession = Depends(get_db),
    ) -> dict:
        if not _managed_cloud():
            return tenant
        st = await execution_allowance_status(db, tenant["tenant_id"])
        if st["hard_exceeded"]:
            raise HTTPException(
                status_code=429,
                detail=(
                    f"Execution allowance hard cap reached for the '{st['plan']}' plan "
                    f"({st['used']} used, cap {st['hard_cap']}). Upgrade the plan or "
                    f"contact billing to raise the cap."
                ),
            )
        return tenant

    return _checker


if __name__ == "__main__":  # allowance soft/hard threshold self-check
    assert _allowance_verdict(600, 500) == {
        "used": 600, "allowance": 500, "hard_cap": 1500,
        "soft_exceeded": True, "hard_exceeded": False,
    }
    assert _allowance_verdict(1500, 500)["hard_exceeded"]
    assert not _allowance_verdict(10, 500)["soft_exceeded"]
    assert _allowance_verdict(0, 0) == {
        "used": 0, "allowance": 0, "hard_cap": 0,
        "soft_exceeded": False, "hard_exceeded": False,
    }
    print("entitlements allowance self-check ok")
