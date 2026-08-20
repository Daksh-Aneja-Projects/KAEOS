"""KAEOS HR V1 — connectors

Outbound HR connectors (BambooHR directory sync).
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_security_event
from app.core.database import get_db
from app.core.tenant import approver_identity, require_role

router = APIRouter()


# ── BambooHR Connector ─────────────────────────────────────────────────────────

class BambooHRSyncBody(BaseModel):
    subdomain: str = Field(..., min_length=1, max_length=64)
    api_key: str = Field(..., min_length=1, max_length=256)


@router.post("/connectors/bamboohr/sync")
async def sync_bamboohr(
    body: BambooHRSyncBody, tenant: dict = Depends(require_role("admin")), db: AsyncSession = Depends(get_db),
):
    """Pull the BambooHR employee directory and upsert it into hr_employees.
    Credentials travel in this request only — nothing is persisted (see
    app/hr/connectors/bamboohr.py:sync_employees; there is no connector
    credential store for HR yet). Admin-only: this both reads and writes
    employee PII. Wires BambooHRConnector, previously never instantiated."""
    from app.hr.connectors.bamboohr import sync_employees
    tenant_id = tenant["tenant_id"]
    result = await sync_employees(db, tenant_id, body.subdomain, body.api_key)
    if not result.get("ok"):
        raise HTTPException(502, detail=result.get("error") or "BambooHR sync failed")
    await record_security_event(tenant_id=tenant_id, event_type="MODIFICATION", action="EXECUTE",
        actor=approver_identity(tenant), actor_role=tenant.get("role"),
        resource_type="hr_connector", resource_id="bamboohr",
        details={"created": result.get("created"), "updated": result.get("updated")})
    return result
