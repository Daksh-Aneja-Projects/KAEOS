"""Add autonomy_policies (the Autonomy Dial) + RLS.

Per-tenant, per-domain autonomy risk appetite that Gate 3 (confidence → HITL)
reads at runtime. Tenant-scoped, so it goes under the standard RLS policy on
Postgres. Idempotent.

Revision ID: 0007_autonomy_policies
Revises: 0006_state_append_only
Create Date: 2026-07-24
"""
from alembic import op

from app.models.settings import AutonomyPolicy
from app.core.rls import rls_enable_statements

revision = "0007_autonomy_policies"
down_revision = "0006_state_append_only"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    AutonomyPolicy.__table__.create(bind=bind, checkfirst=True)
    if bind.dialect.name == "postgresql":
        from sqlalchemy import text
        for stmt in rls_enable_statements("autonomy_policies"):
            bind.execute(text(stmt))


def downgrade() -> None:
    AutonomyPolicy.__table__.drop(bind=op.get_bind(), checkfirst=True)
