"""KAEOS baseline schema — single source of truth.

This replaces the previous 8-migration chain, which could NOT build the schema
on its own: it assumed ``Base.metadata.create_all`` (init_db) had already run
and was a set of additive, order-dependent deltas. Running ``alembic upgrade
head`` on a fresh database produced 3 tables and then crashed on an unguarded
ALTER (``no such table: config_mcp_tools``).

This baseline builds the ENTIRE current model schema directly from the ORM
metadata, so ``alembic upgrade head`` alone produces a complete, correct
database on any fresh install — and it stays in lock-step with the models by
construction. On PostgreSQL it also enables pgvector and installs row-level
security on every tenant-scoped table.

Existing databases that were stamped at the old head (f2b6c1d4e7a8) should be
re-stamped once with:  ``alembic stamp 0001_baseline``.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-07-19
"""
from alembic import op

from app.models.domain import Base
# Importing app.core.database registers every model module with Base.metadata
# (it imports app.models.*, app.hr.*, app.finance.*, … in one place).
import app.core.database  # noqa: F401
from app.core.rls import (
    GLOBAL_TABLES,
    UNPROTECTED_TENANT_TABLES_SQL,
    rls_enable_statements,
)

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    if is_pg:
        # Semantic-memory tables use pgvector's `vector` type.
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # Build the full current schema. checkfirst=True → idempotent, so this is
    # safe even if some tables already exist (e.g. init_db ran first in dev).
    Base.metadata.create_all(bind=bind, checkfirst=True)

    if is_pg:
        # Put every tenant-scoped table under RLS (the app connects as a
        # non-owner role, so these policies actually apply). Idempotent.
        rows = bind.execute(__import__("sqlalchemy").text(UNPROTECTED_TENANT_TABLES_SQL)).fetchall()
        from sqlalchemy import text
        for (table,) in rows:
            if table in GLOBAL_TABLES:
                continue
            for stmt in rls_enable_statements(table):
                bind.execute(text(stmt))


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
