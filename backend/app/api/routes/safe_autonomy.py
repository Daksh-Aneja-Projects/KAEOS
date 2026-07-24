"""Safe Autonomy Rate - the north-star metric, exposed for the executive view."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.tenant import get_tenant_id
from app.services.safe_autonomy import compute_safe_autonomy
from app.services.forecast import linear_forecast

router = APIRouter(prefix="/metrics", tags=["Metrics"])


@router.get("/safe-autonomy")
async def get_safe_autonomy(
    days: int = Query(30, ge=1, le=365),
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Safe-autonomy-rate with its explainable breakdown, per-skill split, and
    daily time-series. Computed live from logged executions for this tenant."""
    return await compute_safe_autonomy(db, tenant_id, days=days)


@router.get("/forecast")
async def get_forecast(
    days: int = Query(45, ge=7, le=365),
    horizon: int = Query(14, ge=1, le=90),
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Precog — forecast the north-star (safe-autonomy-rate) and daily execution
    volume `horizon` days out, with 95% confidence bands, from the real daily
    series. Honest: too little history returns `insufficient`, never a fabricated
    curve."""
    sar = await compute_safe_autonomy(db, tenant_id, days=days)
    ts = sar.get("timeseries", [])
    dates = [p["date"] for p in ts]
    rate_series = [p.get("safe_autonomy_rate") for p in ts]
    volume_series = [p.get("total") for p in ts]

    rate_fc = linear_forecast(rate_series, horizon=horizon, clamp01=True)
    volume_fc = linear_forecast([float(v) if v is not None else None for v in volume_series],
                                horizon=horizon, clamp01=False)

    # Human-readable headline for the north-star projection.
    current = next((r for r in reversed(rate_series) if r is not None), None)
    projected = rate_fc["forecast"][-1]["yhat"] if rate_fc.get("forecast") else None
    direction = None
    if current is not None and projected is not None:
        delta = projected - current
        direction = "improving" if delta > 0.005 else "declining" if delta < -0.005 else "stable"

    return {
        "window_days": days,
        "horizon_days": horizon,
        "dates": dates,
        "safe_autonomy": rate_fc,
        "volume": volume_fc,
        "headline": {
            "current_rate": current,
            "projected_rate": projected,
            "direction": direction,
            "confidence_r2": rate_fc.get("r2"),
        },
    }
