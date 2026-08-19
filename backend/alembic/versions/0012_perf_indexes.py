"""Perf: composite indexes for the hot analytics read paths.

Every analytics endpoint (safe-autonomy, time-machine, causal, regulatory) filters
skill_executions by (tenant_id, started_at), and cost telemetry filters cost_events
by (tenant_id, timestamp). Composite indexes turn those range scans into seeks.
Perf-only — no schema/behavior change.

Inspector-guarded (the 0052 pattern): a table absent from this deployment is
skipped, an index that already exists is skipped, and anything else — a typo in a
name or column, a real SQL error — raises. The previous bare `except Exception:
pass` made those two cases indistinguishable, and since both indexes are declared
in Base.metadata (so 0001's create_all already built them), the swallowed branch
never had to run for the migration to appear to succeed.

Revision ID: 0012_perf_indexes
Revises: 0011_event_mesh
Create Date: 2026-07-25
"""
import sqlalchemy as sa
from alembic import op

revision = "0012_perf_indexes"
down_revision = "0011_event_mesh"
branch_labels = None
depends_on = None

_INDEXES = [
    ("ix_skill_executions_tenant_started", "skill_executions", ["tenant_id", "started_at"]),
    ("ix_cost_events_tenant_ts", "cost_events", ["tenant_id", "timestamp"]),
]


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    tables = set(insp.get_table_names())
    for name, table, cols in _INDEXES:
        if table not in tables:
            continue
        if name in {i["name"] for i in insp.get_indexes(table)}:
            continue
        op.create_index(name, table, cols)


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    tables = set(insp.get_table_names())
    for name, table, _cols in reversed(_INDEXES):
        if table not in tables:
            continue
        if name in {i["name"] for i in insp.get_indexes(table)}:
            op.drop_index(name, table_name=table)
