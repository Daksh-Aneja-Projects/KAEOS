"""KAEOS — Time-series metrics: rollup + snapshot.

The rollup (leader-guarded, wired into the existing scheduler) snapshots each
tenant's current-bucket metrics into ``ts_metric_samples`` so Time Machine /
dashboards read a STORED series instead of reconstructing it on every request.

Metrics captured per bucket:
  * ``safe_autonomy_rate``  — safe-autonomous executions / all executions (0-1)
  * ``execution_volume``    — count of executions in the bucket
  * ``cost_usd``            — summed LLM cost in the bucket

Honesty contract: a metric with NO underlying data in the bucket is not written
at all (no fabricated 0). ``cost_usd`` is tied to whether any cost events exist,
not to execution volume, because a gate-blocked action costs real tokens without
ever producing an execution row.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import SkillExecution
from app.models.infrastructure import CostEvent
from app.models.metrics_ts import MetricSample
from app.services.safe_autonomy import _classify_counts

_INTERVAL_KEYS = ("safe_autonomy_rate", "execution_volume", "cost_usd")


def _bucket_start(interval: str, now: datetime) -> datetime:
    """Truncate ``now`` to the start of its interval bucket (UTC)."""
    now = now.astimezone(timezone.utc)
    if interval == "day":
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    # default "hour"
    return now.replace(minute=0, second=0, microsecond=0)


def _bucket_end(interval: str, start: datetime) -> datetime:
    from datetime import timedelta
    return start + (timedelta(days=1) if interval == "day" else timedelta(hours=1))


async def _bucket_metrics(db: AsyncSession, tenant_id: str,
                          start: datetime, end: datetime) -> dict[str, Decimal]:
    """Compute the metrics present in [start, end) for one tenant.

    Returns only metrics that have underlying data — a key absent here means
    "no data", which the caller must NOT persist as 0.
    """
    metrics: dict[str, Decimal] = {}

    autonomous_safe, *_ = _classify_counts()
    exec_row = (await db.execute(
        select(func.count().label("total"), autonomous_safe.label("safe"))
        .where(SkillExecution.tenant_id == tenant_id,
               SkillExecution.started_at >= start,
               SkillExecution.started_at < end)
    )).one()
    total = int(exec_row.total or 0)
    if total > 0:
        metrics["execution_volume"] = Decimal(total)
        # 4dp mirrors the on-read safe-autonomy rate.
        metrics["safe_autonomy_rate"] = (Decimal(int(exec_row.safe or 0)) / Decimal(total)
                                         ).quantize(Decimal("0.0001"))

    cost_row = (await db.execute(
        select(func.count().label("n"),
               func.coalesce(func.sum(CostEvent.cost_usd), 0).label("s"))
        .where(CostEvent.tenant_id == tenant_id,
               CostEvent.timestamp >= start,
               CostEvent.timestamp < end)
    )).one()
    if int(cost_row.n or 0) > 0:   # cost events exist → the sum is real (even if 0.00)
        metrics["cost_usd"] = Decimal(str(cost_row.s or 0))

    return metrics


async def snapshot_tenant(db: AsyncSession, tenant_id: str, *,
                          interval: str = "hour",
                          now: Optional[datetime] = None) -> int:
    """Append the current-bucket samples for one tenant. Idempotent.

    Returns the number of NEW rows written (0 if the bucket was already captured
    or the tenant had no data this bucket).
    """
    now = now or datetime.now(timezone.utc)
    start = _bucket_start(interval, now)
    end = _bucket_end(interval, start)

    metrics = await _bucket_metrics(db, tenant_id, start, end)
    if not metrics:
        return 0

    # Idempotency: skip metrics already written for this exact bucket. Cheap
    # pre-check select keeps it dialect-portable (no ON CONFLICT); the unique
    # constraint is the backstop against a racing second leader.
    existing = set((await db.execute(
        select(MetricSample.metric_key).where(
            MetricSample.tenant_id == tenant_id,
            MetricSample.interval == interval,
            MetricSample.bucket_start == start,
            MetricSample.metric_key.in_(list(metrics.keys())),
        )
    )).scalars().all())

    written = 0
    for key, value in metrics.items():
        if key in existing:
            continue
        db.add(MetricSample(tenant_id=tenant_id, metric_key=key, value=value,
                            interval=interval, bucket_start=start))
        written += 1
    if written:
        await db.commit()
    return written


async def run_metrics_rollup(interval: str = "hour") -> int:
    """Leader-guarded rollup: snapshot every active tenant's current bucket.

    Mirrors ``run_usage_metering``: enumerate tenants on the owner session, then
    snapshot each under its own RLS context on the normal session. Returns total
    rows written across tenants.
    """
    from app.services.leader_lock import leader_lock
    try:
        if not leader_lock.is_leader:
            return 0
    except Exception:
        pass  # no leader machinery → single instance → proceed

    from app.core.context import current_tenant_id
    from app.core.database import AsyncSessionLocal, MaintenanceSessionLocal

    # Enumerate ALL active tenants (not just those with a SkillExecution row):
    # this rollup also records cost_usd, which a tenant can incur on gate-blocked
    # actions that never produced an execution row. snapshot_tenant only writes a
    # sample when there is real data, so a no-activity tenant costs a cheap query
    # and writes nothing (honesty contract preserved).
    from app.models.auth import Tenant
    async with MaintenanceSessionLocal() as mdb:
        tenant_ids = [t for t in (await mdb.execute(
            select(Tenant.tenant_id).where(Tenant.is_active.is_(True))
        )).scalars().all() if t]

    total = 0
    for tid in tenant_ids:
        token = current_tenant_id.set(tid)
        try:
            async with AsyncSessionLocal() as db:
                total += await snapshot_tenant(db, tid, interval=interval)
        except Exception:
            import logging
            logging.getLogger(__name__).warning(
                "[MetricsRollup] snapshot failed for tenant %s", tid, exc_info=True)
        finally:
            current_tenant_id.reset(token)
    return total
