"""Add collaboration + automation tables (Sprints 6-10) + RLS.

Adds four tenant-scoped side-tables that hang off workflow entities:
  core_workflow_assignments, core_workflow_comments, core_saved_segments,
  core_automation_rules.

Incremental revision for databases already stamped at ``0004_workflow``; a
fresh ``alembic upgrade head`` builds them from ORM metadata in the baseline.
On Postgres each is placed under the same tenant-isolation policy as every
other tenant-scoped table. Idempotent.

Revision ID: 0005_workspace
Revises: 0004_workflow
Create Date: 2026-07-21
"""
from alembic import op

import app.core.database  # noqa: F401 — registers all models on Base.metadata
from app.core.collaboration import WorkflowAssignment, WorkflowComment, SavedSegment
from app.core.automation import AutomationRule
from app.core.rls import rls_enable_statements

revision = "0005_workspace"
down_revision = "0004_workflow"
branch_labels = None
depends_on = None

_TABLES = [
    (WorkflowAssignment, "core_workflow_assignments"),
    (WorkflowComment, "core_workflow_comments"),
    (SavedSegment, "core_saved_segments"),
    (AutomationRule, "core_automation_rules"),
]


def upgrade() -> None:
    bind = op.get_bind()
    for model, table in _TABLES:
        model.__table__.create(bind=bind, checkfirst=True)
        if bind.dialect.name == "postgresql":
            from sqlalchemy import text
            for stmt in rls_enable_statements(table):
                bind.execute(text(stmt))


def downgrade() -> None:
    bind = op.get_bind()
    for model, _ in reversed(_TABLES):
        model.__table__.drop(bind=bind, checkfirst=True)
