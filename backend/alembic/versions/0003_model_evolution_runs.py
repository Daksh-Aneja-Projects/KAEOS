"""Add model_evolution_runs (AI Foundry Phase 3) + RLS.

Incremental revision for databases already stamped at ``0002_retention``; a fresh
``alembic upgrade head`` builds the table from ORM metadata in the baseline. On
Postgres it is placed under the same tenant-isolation policy as every other
tenant-scoped table. Idempotent.

Revision ID: 0003_evolution
Revises: 0002_retention
Create Date: 2026-07-21
"""
from alembic import op

import app.core.database  # noqa: F401 — registers all models on Base.metadata
from app.models.foundry import ModelEvolutionRun
from app.core.rls import rls_enable_statements

revision = "0003_evolution"
down_revision = "0002_retention"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    ModelEvolutionRun.__table__.create(bind=bind, checkfirst=True)

    if bind.dialect.name == "postgresql":
        from sqlalchemy import text
        for stmt in rls_enable_statements("model_evolution_runs"):
            bind.execute(text(stmt))


def downgrade() -> None:
    bind = op.get_bind()
    ModelEvolutionRun.__table__.drop(bind=bind, checkfirst=True)
