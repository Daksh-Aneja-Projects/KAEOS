"""Add retention_policies (configurable data-retention windows) + RLS.

The baseline builds the whole schema from ORM metadata, so a FRESH
``alembic upgrade head`` already includes this table. This incremental revision
exists for databases already stamped at ``0001_baseline``: it creates the one
new table and, on Postgres, puts it under the same tenant-isolation policy every
other tenant-scoped table carries. Idempotent (checkfirst / IF EXISTS), so it is
safe even when runtime ``init_db`` created the table first.

Revision ID: 0002_retention
Revises: 0001_baseline
Create Date: 2026-07-21
"""
from alembic import op

# Registering the models puts RetentionPolicy on Base.metadata.
import app.core.database  # noqa: F401
from app.models.settings import RetentionPolicy
from app.core.rls import rls_enable_statements

revision = "0002_retention"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    RetentionPolicy.__table__.create(bind=bind, checkfirst=True)

    if bind.dialect.name == "postgresql":
        from sqlalchemy import text
        for stmt in rls_enable_statements("retention_policies"):
            bind.execute(text(stmt))


def downgrade() -> None:
    bind = op.get_bind()
    RetentionPolicy.__table__.drop(bind=bind, checkfirst=True)
