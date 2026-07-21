"""KAEOS — Privacy & data-lifecycle API (GDPR Art.17 erasure, Art.5 retention).

Exposes two capabilities the platform previously had as service code only:

  POST /privacy/erasure            Right-to-erasure for a single data subject.
  GET  /privacy/retention          Effective retention policies + a dry-run preview.
  PUT  /privacy/retention          Configure a retention window for a data class.
  POST /privacy/retention/apply    Enforce retention now (dry-run by default).

Erasure and any real (non-dry-run) purge are admin-gated and audit-logged. The
retention allow-list lives in app/services/retention.py and cannot target the
provenance ledger or the Foundry training lineage.
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_security_event
from app.core.database import get_db
from app.core.tenant import get_tenant_id, require_role
from app.services import retention
from app.services.privacy_erasure import erase_subject

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/privacy", tags=["Privacy & Data Lifecycle"])


# ── Right-to-erasure (GDPR Art.17) ───────────────────────────────────────────

class ErasureRequest(BaseModel):
    employee_id: Optional[str] = None
    email: Optional[str] = None


@router.post("/erasure")
async def erase_data_subject(
    body: ErasureRequest,
    tenant: dict = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Irreversibly anonymise a single data subject on the HR PII tables.

    Requires admin. At least one of ``employee_id`` / ``email`` is required.
    Returns a per-table receipt. See the service docstring for the honest
    coverage boundary (object-storage blobs and the hash-chained ledger's hashed
    references are retained by design).
    """
    tenant_id = tenant["tenant_id"]
    if not (body.employee_id or body.email):
        raise HTTPException(400, "Provide at least one of employee_id / email")
    try:
        receipt = await erase_subject(
            db, tenant_id, employee_id=body.employee_id, email=body.email,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))

    await record_security_event(
        tenant_id=tenant_id, event_type="MODIFICATION", action="DELETE",
        actor=tenant.get("name"), actor_role=tenant.get("role"),
        resource_type="privacy_erasure",
        resource_id=body.employee_id or "by-email",
        details={"rows_anonymised": receipt.get("total_rows_anonymised", 0)},
    )
    return receipt


# ── Retention windows (GDPR Art.5(1)(e) storage limitation) ──────────────────

class RetentionSet(BaseModel):
    data_class: str
    enabled: bool
    retain_days: Optional[int] = None   # null → inherit the registry default


@router.get("/retention")
async def get_retention(
    preview: bool = True,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """List effective retention policies. With ``preview=true`` (default) also
    returns how many rows each enabled class WOULD purge right now (no deletion)."""
    policies = await retention.list_effective(db, tenant_id)
    out: dict = {"policies": policies}
    if preview:
        out["preview"] = await retention.apply_for_tenant(db, tenant_id, dry_run=True)
    return out


@router.put("/retention")
async def set_retention(
    body: RetentionSet,
    tenant: dict = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Configure the retention window for one data class. Requires admin."""
    tenant_id = tenant["tenant_id"]
    try:
        result = await retention.set_policy(
            db, tenant_id, body.data_class,
            retain_days=body.retain_days, enabled=body.enabled,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))

    await record_security_event(
        tenant_id=tenant_id, event_type="CONFIG_CHANGE", action="WRITE",
        actor=tenant.get("name"), actor_role=tenant.get("role"),
        resource_type="retention_policy", resource_id=body.data_class,
        details=result,
    )
    return result


@router.post("/retention/apply")
async def apply_retention(
    dry_run: bool = True,
    tenant: dict = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Enforce retention for this tenant now. Dry-run by default (counts only).

    Pass ``dry_run=false`` to actually hard-delete rows past their window.
    Requires admin; a real purge is audit-logged."""
    tenant_id = tenant["tenant_id"]
    receipt = await retention.apply_for_tenant(db, tenant_id, dry_run=dry_run)

    if not dry_run:
        await record_security_event(
            tenant_id=tenant_id, event_type="MODIFICATION", action="DELETE",
            actor=tenant.get("name"), actor_role=tenant.get("role"),
            resource_type="retention_sweep", resource_id="apply",
            details={"total_rows_deleted": receipt.get("total", 0)},
        )
    return receipt
