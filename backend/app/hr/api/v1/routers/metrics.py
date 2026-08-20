"""KAEOS HR V1 — metrics

HR metric snapshots: the stored time series and the daily upsert.
"""
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.tenant import get_tenant_id, require_role
from app.hr.models.analytics import HRMetricSnapshot
from app.hr.services.analytics import hr_metric_snapshot

router = APIRouter()


# ── HR Analytics Snapshots ──────────────────────────────────────────────────────

@router.get("/hr-metrics")
async def list_hr_metrics(
    days: int = 180, tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db),
):
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).date()
    rows = (await db.execute(
        select(HRMetricSnapshot).where(
            HRMetricSnapshot.tenant_id == tenant_id, HRMetricSnapshot.snapshot_date >= cutoff,
        ).order_by(HRMetricSnapshot.snapshot_date.asc()).limit(400)
    )).scalars().all()
    return [{
        "id": s.id, "snapshot_date": s.snapshot_date.isoformat() if s.snapshot_date else None,
        "total_headcount": s.total_headcount, "active_contractors": s.active_contractors,
        "voluntary_turnover_ytd": s.voluntary_turnover_ytd, "involuntary_turnover_ytd": s.involuntary_turnover_ytd,
        "open_requisitions": s.open_requisitions, "time_to_fill_avg_days": s.time_to_fill_avg_days,
        "offer_acceptance_rate": s.offer_acceptance_rate, "diversity_metrics": s.diversity_metrics or {},
        "total_payroll_run_rate": s.total_payroll_run_rate,
    } for s in rows]


@router.post("/hr-metrics/snapshot", status_code=201)
async def generate_hr_metric_snapshot(
    tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    """Compute today's HR metric snapshot from real current rows (upserts if
    one already exists for today). Fields with no real data source (e.g.
    voluntary vs involuntary turnover split — HREmployee has no termination
    reason) stay null rather than a fabricated number."""
    snap = await hr_metric_snapshot(db, tenant["tenant_id"])
    return {"id": snap.id, "snapshot_date": snap.snapshot_date.isoformat(), "total_headcount": snap.total_headcount}
