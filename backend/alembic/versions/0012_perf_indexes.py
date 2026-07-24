"""Perf: composite indexes for the hot analytics read paths.

Every analytics endpoint (safe-autonomy, time-machine, causal, regulatory) filters
skill_executions by (tenant_id, started_at), and cost telemetry filters cost_events
by (tenant_id, timestamp). Composite indexes turn those range scans into seeks.
Perf-only — no schema/behavior change. Idempotent (IF NOT EXISTS), so it is safe on
SQLite and Postgres and on a DB that already has the index from create_all.

Revision ID: 0012_perf_indexes
Revises: 0011_event_mesh
Create Date: 2026-07-25
"""
from alembic import op
from sqlalchemy import text

revision = "0012_perf_indexes"
down_revision = "0011_event_mesh"
branch_labels = None
depends_on = None

_INDEXES = [
    ("ix_skill_executions_tenant_started", "skill_executions", "tenant_id, started_at"),
    ("ix_cost_events_tenant_ts", "cost_events", "tenant_id, timestamp"),
]


def upgrade() -> None:
    bind = op.get_bind()
    for name, table, cols in _INDEXES:
        try:
            bind.execute(text(f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({cols})"))
        except Exception:
            # A table that doesn't exist in this deployment (or a dialect quirk) must
            # not fail the migration — the index is a pure optimization.
            pass


def downgrade() -> None:
    bind = op.get_bind()
    for name, _table, _cols in _INDEXES:
        try:
            bind.execute(text(f"DROP INDEX IF EXISTS {name}"))
        except Exception:
            pass
