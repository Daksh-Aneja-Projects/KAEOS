"""Time-series metrics store: recorded metric samples per tenant.

Backs app/services/metrics_timeseries.py (leader-guarded rollup) so Time Machine
and dashboards read a stored series instead of reconstructing on read. Additive +
inspector-guarded; RLS is Postgres-only (SQLite dev builds via create_all).

Revision ID: 0043_metrics_timeseries
Revises: 0042_lending_vertical
Create Date: 2026-08-14
"""
import sqlalchemy as sa
from alembic import op

from app.core.rls import rls_enable_statements

revision = "0043_metrics_timeseries"
down_revision = "0042_lending_vertical"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    pg = bind.dialect.name == "postgresql"
    tables = set(insp.get_table_names())

    if "ts_metric_samples" not in tables:
        op.create_table(
            "ts_metric_samples",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), nullable=False, index=True),
            sa.Column("metric_key", sa.String(length=48), nullable=False),
            sa.Column("value", sa.Numeric(18, 6), nullable=False),
            sa.Column("interval", sa.String(length=8), nullable=False),
            sa.Column("bucket_start", sa.DateTime(timezone=True), nullable=False),
            sa.Column("captured_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.UniqueConstraint("tenant_id", "metric_key", "interval", "bucket_start",
                                name="uq_ts_sample_bucket"),
        )
        op.create_index("ix_ts_metric_samples_lookup", "ts_metric_samples",
                        ["tenant_id", "metric_key", "bucket_start"])
        if pg:
            for stmt in rls_enable_statements("ts_metric_samples"):
                op.execute(stmt)


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "ts_metric_samples" in set(insp.get_table_names()):
        op.drop_table("ts_metric_samples")
