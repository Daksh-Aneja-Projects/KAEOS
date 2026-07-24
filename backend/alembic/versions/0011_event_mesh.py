"""Add external_signals (Sense-Decide-Act Event Mesh) + RLS.

Tenant-scoped external-world signals correlated to the twin. RLS on Postgres.
Idempotent.

Revision ID: 0011_event_mesh
Revises: 0010_missions
Create Date: 2026-07-24
"""
from alembic import op

from app.models.event_mesh import ExternalSignal
from app.core.rls import rls_enable_statements

revision = "0011_event_mesh"
down_revision = "0010_missions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    ExternalSignal.__table__.create(bind=bind, checkfirst=True)
    if bind.dialect.name == "postgresql":
        from sqlalchemy import text
        for stmt in rls_enable_statements("external_signals"):
            bind.execute(text(stmt))


def downgrade() -> None:
    ExternalSignal.__table__.drop(bind=op.get_bind(), checkfirst=True)
