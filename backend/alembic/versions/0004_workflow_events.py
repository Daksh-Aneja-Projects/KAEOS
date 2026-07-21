"""Add core_workflow_events (shared domain workflow engine) + RLS.

Incremental revision for databases already stamped at ``0003_evolution``; a
fresh ``alembic upgrade head`` builds the table from ORM metadata in the
baseline. On Postgres it is placed under the same tenant-isolation policy as
every other tenant-scoped table. Idempotent.

Revision ID: 0004_workflow
Revises: 0003_evolution
Create Date: 2026-07-21
"""
from alembic import op

import app.core.database  # noqa: F401 — registers all models on Base.metadata
from app.core.workflow import WorkflowEvent
from app.core.rls import rls_enable_statements

revision = "0004_workflow"
down_revision = "0003_evolution"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    WorkflowEvent.__table__.create(bind=bind, checkfirst=True)

    if bind.dialect.name == "postgresql":
        from sqlalchemy import text
        for stmt in rls_enable_statements("core_workflow_events"):
            bind.execute(text(stmt))


def downgrade() -> None:
    bind = op.get_bind()
    WorkflowEvent.__table__.drop(bind=bind, checkfirst=True)
