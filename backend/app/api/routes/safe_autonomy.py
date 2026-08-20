"""Safe Autonomy Rate - the north-star metric, exposed for the executive view."""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.tenant import get_tenant_id
from app.services.safe_autonomy import compute_safe_autonomy
from app.services.forecast import linear_forecast

router = APIRouter(prefix="/metrics", tags=["Metrics"])


@router.get("/latency")
async def get_latency(
    hours: int = Query(24, ge=1, le=168),
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Where the seconds go: model-call latency by tier/model (from CostEvent)
    plus per-gate wall-time for recent executions (in-process ring buffer)."""
    from app.models.infrastructure import CostEvent

    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    rows = (await db.execute(
        select(CostEvent.model_tier, CostEvent.model_name, CostEvent.latency_ms)
        .where(CostEvent.tenant_id == tenant_id, CostEvent.timestamp >= cutoff)
        .order_by(CostEvent.timestamp.desc())
        .limit(2000)
    )).all()

    def agg(samples: list[int]) -> dict:
        samples = sorted(samples)
        n = len(samples)
        return {
            "calls": n,
            "avg_ms": int(sum(samples) / n),
            "p50_ms": samples[n // 2],
            "p95_ms": samples[min(n - 1, int(n * 0.95))],
            "max_ms": samples[-1],
        }

    by_tier: dict[str, list[int]] = {}
    by_model: dict[str, list[int]] = {}
    for tier, model, ms in rows:
        if ms is None:
            continue
        by_tier.setdefault(tier or "unspecified", []).append(ms)
        by_model.setdefault(model or "unknown", []).append(ms)

    from app.agents.runtime import recent_stage_timings
    recent = recent_stage_timings(tenant_id)

    return {
        "window_hours": hours,
        "model_calls": {k: agg(v) for k, v in by_tier.items()},
        "by_model": {k: agg(v) for k, v in by_model.items()},
        "recent_executions": recent[-20:],
        "note": (
            "model_calls is measured wall-time per LLM call from metering; "
            "recent_executions shows per-gate wall-time for the last executions "
            "in this process."
        ),
    }


@router.get("/safe-autonomy")
async def get_safe_autonomy(
    days: int = Query(30, ge=1, le=365),
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Safe-autonomy-rate with its explainable breakdown, per-skill split, and
    daily time-series. Computed live from logged executions for this tenant."""
    return await compute_safe_autonomy(db, tenant_id, days=days)


@router.get("/timeseries")
async def get_timeseries(
    metric: str = Query("safe_autonomy_rate",
                        description="safe_autonomy_rate | cost_usd | execution_volume"),
    from_: datetime | None = Query(None, alias="from"),
    to: datetime | None = Query(None),
    interval: str = Query("hour", pattern="^(hour|day)$"),
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """The STORED metric series for the caller's tenant (from the rollup), so
    Time Machine / dashboards read a real recorded series instead of
    reconstructing it on every request. Honest: a metric with no stored samples
    returns an empty series with a note, never a fabricated 0 line."""
    from app.models.metrics_ts import MetricSample

    to = to or datetime.now(timezone.utc)
    from_ = from_ or (to - timedelta(days=30))
    # Bound the window so a caller cannot request years of hourly samples in one
    # shot. Clamp the span to 400 days and cap the row count.
    if (to - from_) > timedelta(days=400):
        from_ = to - timedelta(days=400)

    rows = (await db.execute(
        select(MetricSample.bucket_start, MetricSample.value)
        .where(MetricSample.tenant_id == tenant_id,
               MetricSample.metric_key == metric,
               MetricSample.interval == interval,
               MetricSample.bucket_start >= from_,
               MetricSample.bucket_start <= to)
        .order_by(MetricSample.bucket_start)
        .limit(10000)
    )).all()

    series = [{"captured_at": bucket.isoformat(), "value": float(value)}
              for bucket, value in rows]
    return {
        "metric": metric,
        "interval": interval,
        "from": from_.isoformat(),
        "to": to.isoformat(),
        "series": series,
        "note": (None if series else
                 "No stored samples for this metric/window; the rollup writes a "
                 "sample only when the metric has underlying data (never a 0)."),
    }


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
