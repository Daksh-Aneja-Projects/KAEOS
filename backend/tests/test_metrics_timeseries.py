"""Time-series metrics store: rollup writes a real series, idempotently, honestly.

Covers the three contract points:
  * a sample is written by the rollup and queried back tenant-scoped
  * the rollup is idempotent (a second run does not double-count a bucket)
  * a no-data metric yields an empty series with a note, never a fabricated 0
"""
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select

from app.core.database import get_db
from app.core.tenant import get_tenant_id
from app.main import app
from app.models.domain import SkillExecution
from app.models.infrastructure import CostEvent
from app.models.metrics_ts import MetricSample  # noqa: F401 — registers table for create_all
from app.services.metrics_timeseries import _bucket_start, snapshot_tenant

# A time comfortably inside the current hour bucket (mid-hour avoids edge races).
_NOW = _bucket_start("hour", datetime.now(timezone.utc)).replace(minute=30)


async def _exec(db, tenant, *, hitl_required, status):
    db.add(SkillExecution(
        id=str(uuid.uuid4()), skill_id_name="refund", tenant_id=tenant,
        status=status, hitl_required=hitl_required, outcome_type=status,
        started_at=_NOW,
    ))
    await db.commit()


async def _cost(db, tenant, usd):
    db.add(CostEvent(
        id=str(uuid.uuid4()), tenant_id=tenant, model_name="qwen", model_tier="FAST",
        cost_usd=Decimal(str(usd)), timestamp=_NOW,
    ))
    await db.commit()


async def test_sample_written_and_queried_back_tenant_scoped(db, async_client):
    t = "tenant_ts_a"
    # 3 executions: 2 safe-autonomous, 1 routed to human → rate 2/3.
    await _exec(db, t, hitl_required=False, status="SUCCESS_CLEAN")
    await _exec(db, t, hitl_required=False, status="SUCCESS_CLEAN")
    await _exec(db, t, hitl_required=True, status="SUCCESS_CLEAN")
    await _cost(db, t, "1.250000")
    # A different tenant's data must not leak into t's series.
    await _exec(db, "tenant_ts_other", hitl_required=False, status="SUCCESS_CLEAN")

    written = await snapshot_tenant(db, t, interval="hour", now=_NOW)
    assert written == 3  # safe_autonomy_rate, execution_volume, cost_usd

    rows = {r.metric_key: r.value for r in (await db.execute(
        select(MetricSample).where(MetricSample.tenant_id == t)
    )).scalars().all()}
    assert rows["execution_volume"] == Decimal("3")
    assert rows["safe_autonomy_rate"] == Decimal("0.6667")
    assert rows["cost_usd"] == Decimal("1.250000")

    # Query API returns the stored series for the caller's tenant only.
    app.dependency_overrides[get_tenant_id] = lambda: t
    try:
        resp = await async_client.get("/api/v1/metrics/timeseries",
                                      params={"metric": "safe_autonomy_rate", "interval": "hour"})
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["series"]) == 1
        assert body["series"][0]["value"] == 0.6667
        assert body["note"] is None
    finally:
        app.dependency_overrides.pop(get_tenant_id, None)


async def test_rollup_idempotent_per_bucket(db):
    t = "tenant_ts_idem"
    await _exec(db, t, hitl_required=False, status="SUCCESS_CLEAN")
    await _cost(db, t, "0.500000")

    first = await snapshot_tenant(db, t, interval="hour", now=_NOW)
    second = await snapshot_tenant(db, t, interval="hour", now=_NOW)
    assert first > 0
    assert second == 0  # same bucket → nothing new

    n = (await db.execute(
        select(func.count()).select_from(MetricSample)
        .where(MetricSample.tenant_id == t, MetricSample.metric_key == "execution_volume")
    )).scalar_one()
    assert n == 1  # one row per (tenant, metric, bucket), not two


async def test_no_data_metric_is_empty_not_zero(db, async_client):
    t = "tenant_ts_empty"
    # No executions, no cost events → nothing to snapshot.
    written = await snapshot_tenant(db, t, interval="hour", now=_NOW)
    assert written == 0

    app.dependency_overrides[get_tenant_id] = lambda: t
    try:
        resp = await async_client.get("/api/v1/metrics/timeseries",
                                      params={"metric": "safe_autonomy_rate"})
        body = resp.json()
        assert body["series"] == []      # empty, NOT a fabricated 0-point line
        assert body["note"] is not None  # null-with-note
    finally:
        app.dependency_overrides.pop(get_tenant_id, None)
