"""Make Enterprise State append-only (drop unique constraint on tenant_id).

The es_*_state tables were designed as a point-in-time time-series (they carry a
``snapshot_at`` column and ``StateService.get_state`` reads the latest row), but a
``UNIQUE`` index on ``tenant_id`` forced exactly one row per tenant and pushed
``mutate_state`` into an in-place update — destroying history. This migration drops
the unique index and recreates a plain (non-unique) index so many snapshots per
tenant can coexist; ``get_state`` continues to return the most recent by
``snapshot_at``.

This is the first migration authored with real ``op`` DDL (drop_index/create_index)
rather than ``metadata.create_all`` — establishing forward-only migration discipline.

Revision ID: 0006_state_append_only
Revises: 0005_workspace
Create Date: 2026-07-24
"""
from alembic import op
from sqlalchemy import inspect as sa_inspect

revision = "0006_state_append_only"
down_revision = "0005_workspace"
branch_labels = None
depends_on = None

_TABLES = ("es_finance_state", "es_hr_state", "es_ops_state", "es_it_state")


def _recreate_tenant_index(table: str, *, unique: bool) -> None:
    """Drop and recreate ``ix_<table>_tenant_id`` with the given uniqueness.

    Uses raw ``DROP/CREATE INDEX IF (NOT) EXISTS`` — deterministic and idempotent
    on both SQLite and Postgres (the ``index=True, unique=True`` column produces a
    standalone index named ``ix_<table>_tenant_id`` on both, so DROP INDEX applies).
    """
    if table not in sa_inspect(op.get_bind()).get_table_names():
        return
    keyword = "UNIQUE " if unique else ""
    op.execute(f"DROP INDEX IF EXISTS ix_{table}_tenant_id")
    op.execute(f"CREATE {keyword}INDEX IF NOT EXISTS ix_{table}_tenant_id ON {table} (tenant_id)")


def upgrade() -> None:
    for table in _TABLES:
        _recreate_tenant_index(table, unique=False)


def downgrade() -> None:
    for table in _TABLES:
        _recreate_tenant_index(table, unique=True)
