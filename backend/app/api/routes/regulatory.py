"""Regulatory & Risk Autopilot API (v3 Phase 6)."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.tenant import get_tenant_id
from app.services.regulatory import build_overview, evidence_pack, FRAMEWORKS

router = APIRouter(prefix="/regulatory", tags=["Regulatory"])


@router.get("/overview")
async def regulatory_overview(
    days: int = 30,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Control coverage, EU-AI-Act-style risk register, and the live compliance
    monitor — computed from real skills and executions."""
    return await build_overview(db, tenant_id, days=max(1, min(365, days)))


@router.get("/evidence/{framework}")
async def regulatory_evidence(
    framework: str,
    days: int = 90,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Assemble an audit-ready evidence pack for a framework from the real
    provenance + actions ledgers and control executions."""
    if framework.upper() not in FRAMEWORKS:
        raise HTTPException(status_code=404, detail=f"unknown framework; known: {sorted(FRAMEWORKS)}")
    pack = await evidence_pack(db, tenant_id, framework, days=max(1, min(365, days)))
    pack["generated_at"] = datetime.now(timezone.utc).isoformat()
    return pack
