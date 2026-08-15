"""Tenant registry — idempotent registration of valid tenants.

The `tenants` table (app/models/auth.Tenant) is the single source of truth for
which tenant_ids are legitimate. Call ensure_tenant() wherever a tenant comes
into existence (seeding, onboarding, admin bootstrap) so the registry stays
authoritative and offboarding/orphan-detection have a real anchor.
"""
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def ensure_tenant(db: AsyncSession, tenant_id: str, name: str = "",
                        plan: str = "standard") -> None:
    """Register a tenant if not already present (idempotent). Never raises for
    a duplicate; a registry failure must not block the caller's real work."""
    if not tenant_id:
        return
    from app.models.auth import Tenant
    try:
        existing = (await db.execute(
            select(Tenant).where(Tenant.tenant_id == tenant_id)
        )).scalar_one_or_none()
        if existing:
            if name and existing.name != name:
                existing.name = name
                await db.commit()
            return
        db.add(Tenant(tenant_id=tenant_id, name=name or tenant_id, plan=plan))
        await db.commit()
        logger.info("[TenantRegistry] registered tenant %s", tenant_id)
        # Managed cloud: give every new tenant a default LLM spend ceiling up
        # front, so an un-provisioned tenant can never burn tokens unbounded
        # (check_budget ALLOWs when no budget row exists). Self-host stays
        # uncapped by design. Best-effort: a budget failure must not block
        # registration.
        from app.core.config import get_settings
        settings = get_settings()
        if settings.KAEOS_MANAGED_CLOUD:
            try:
                from app.services.cost_governor import CostGovernorService
                await CostGovernorService.create_budget(
                    db, tenant_id,
                    token_limit=settings.DEFAULT_TENANT_TOKEN_LIMIT,
                    cost_limit_usd=settings.DEFAULT_TENANT_COST_LIMIT_USD,
                )
            except Exception as be:
                logger.warning(
                    "[TenantRegistry] default budget not provisioned for %s: %s",
                    tenant_id, be)
    except Exception as e:  # pragma: no cover - registry is best-effort
        logger.warning("[TenantRegistry] could not register %s: %s", tenant_id, e)
        try:
            await db.rollback()
        except Exception:
            # Best-effort cleanup of an already-failed session (it may be closed
            # or its connection dropped). The outer failure is already logged;
            # a rollback failure adds no actionable information.
            pass


async def deactivate_tenant(db: AsyncSession, tenant_id: str,
                            purge: bool = False) -> bool:
    """Mark a tenant inactive (offboarding anchor). Returns True if found.

    When ``purge=True`` this ALSO hard-deletes every tenant-scoped row via
    ``privacy_erasure.purge_tenant`` — the Art.28 processor-offboarding path.
    This is IRREVERSIBLE, so it defaults to False; deactivation stays a safe,
    reversible flag flip unless the caller explicitly opts into erasure.
    """
    from app.models.auth import Tenant
    from app.services.privacy_erasure import purge_tenant
    t = (await db.execute(
        select(Tenant).where(Tenant.tenant_id == tenant_id)
    )).scalar_one_or_none()
    if not t:
        return False
    t.is_active = False
    await db.commit()
    if purge:
        report = await purge_tenant(db, tenant_id)
        logger.info(
            "[TenantRegistry] purged tenant %s on deactivation: %d rows deleted",
            tenant_id, report.get("total_rows_deleted", 0),
        )
    return True
