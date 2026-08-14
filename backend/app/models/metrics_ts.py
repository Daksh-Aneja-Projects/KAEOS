"""KAEOS — Time-series metrics store.

Today the north-star (safe-autonomy-rate), cost, and execution volume are
reconstructed on every read from ``skill_executions`` / ``cost_events``. That is
honest but O(history) per read and gives no stored series to trend against.

``ts_metric_samples`` is the stored series: a leader-guarded rollup appends one
row per (tenant, metric, interval bucket). Tenant-scoped (``tenant_id`` column →
auto-swept into RLS), idempotent per bucket (unique constraint), and HONEST — a
metric with no underlying data in a bucket is simply not written, never a
fabricated 0.
"""
from sqlalchemy import Column, String, Numeric, DateTime, Index, UniqueConstraint
from sqlalchemy.sql import func
import uuid

from app.models.domain import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class MetricSample(Base):
    """One stored metric point for a tenant in one interval bucket."""
    __tablename__ = "ts_metric_samples"
    __table_args__ = (
        # The read path: WHERE tenant_id=? AND metric_key=? AND bucket_start BETWEEN ? AND ?.
        Index("ix_ts_metric_samples_lookup", "tenant_id", "metric_key", "bucket_start"),
        # Idempotency: one row per (tenant, metric, interval, bucket). A re-run of
        # the rollup for a bucket that already has a row is a no-op, so a double
        # tick never double-counts.
        UniqueConstraint("tenant_id", "metric_key", "interval", "bucket_start",
                         name="uq_ts_sample_bucket"),
    )

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    metric_key = Column(String(48), nullable=False)   # safe_autonomy_rate | cost_usd | execution_volume
    value = Column(Numeric(18, 6), nullable=False)
    interval = Column(String(8), nullable=False)       # "hour" | "day"
    bucket_start = Column(DateTime(timezone=True), nullable=False)  # normalized bucket start (UTC)
    captured_at = Column(DateTime(timezone=True), server_default=func.now())
