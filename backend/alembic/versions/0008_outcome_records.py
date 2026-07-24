"""Add outcome_records (the Outcome Intelligence Loop) + RLS.

Measured real-world outcomes of past decisions; tenant-scoped, so it goes under
the standard RLS policy on Postgres. Idempotent.

Revision ID: 0008_outcome_records
Revises: 0007_autonomy_policies
Create Date: 2026-07-24
"""
from alembic import op

from app.models.intelligence_metrics import OutcomeRecord
from app.core.rls import rls_enable_statements

revision = "0008_outcome_records"
down_revision = "0007_autonomy_policies"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    OutcomeRecord.__table__.create(bind=bind, checkfirst=True)
    if bind.dialect.name == "postgresql":
        from sqlalchemy import text
        for stmt in rls_enable_statements("outcome_records"):
            bind.execute(text(stmt))


def downgrade() -> None:
    OutcomeRecord.__table__.drop(bind=op.get_bind(), checkfirst=True)
