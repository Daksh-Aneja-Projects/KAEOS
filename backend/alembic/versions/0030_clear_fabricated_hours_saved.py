"""Clear machine-fabricated hours-saved / cost-saved figures.

Hours-saved needs two tenant inputs KAEOS cannot observe: how long a task took a
person before automation, and that person's loaded hourly cost. Until now
`rollup_department_metrics` derived it anyway, as `tasks_completed * 0.5` hours,
and downstream code multiplied a hardcoded rate onto that to produce a cost.
Both numbers looked measured and had nothing behind them.

The producer no longer writes them, and the read paths now report null-with-note
whenever no baseline exists. But that read-side check keys off "is a value
stored?", so every value the old heuristic already persisted would now be
re-served under `hours_saved_basis: tenant_supplied` - laundering fabricated
figures as tenant-provided ones, which is strictly worse than the original bug.

So the stored values must go. Every non-zero figure in these columns was written
by the heuristic; no code path ever accepted a tenant-supplied value into them,
so this cannot discard real data.

Reset to 0.0 (the column default, read as "no baseline configured") rather than
NULL, so the columns keep their existing NOT NULL/default semantics.

Irreversible by design: the downgrade does NOT restore the fabricated numbers.
Re-inventing them is the defect this migration exists to remove.

Revision ID: 0030_clear_fabricated_hours
Revises: 0029_model_evolution_prompt_hash
Create Date: 2026-08-03
"""
import sqlalchemy as sa
from alembic import op

# Kept <= 32 chars: alembic_version.version_num is VARCHAR(32); Postgres rejects
# a longer id (SQLite silently truncates), which would break `alembic upgrade`.
revision = "0030_clear_fabricated_hours"
down_revision = "0029_model_evolution_prompt_hash"
branch_labels = None
depends_on = None

# table -> columns whose stored values were machine-derived
_FABRICATED = {
    "departments": ("hours_saved_total",),
    "workforce_metrics": ("hours_saved_estimate", "cost_savings_estimate"),
}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    for table, columns in _FABRICATED.items():
        if table not in existing_tables:
            continue
        present = {c["name"] for c in inspector.get_columns(table)}
        for column in columns:
            if column not in present:
                continue
            # Quote via SQLAlchemy so this holds on both SQLite and PostgreSQL.
            op.execute(
                sa.text(f'UPDATE {table} SET {column} = 0.0 WHERE {column} <> 0.0')
            )


def downgrade() -> None:
    """Intentionally a no-op.

    The upgrade removes fabricated data. A downgrade that recomputed
    `tasks_completed * 0.5` would reintroduce exactly the defect being fixed, so
    it does nothing; the columns simply stay at "no baseline configured" until a
    tenant supplies one.
    """
