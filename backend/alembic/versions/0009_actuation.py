"""Add sor_objects + action_records (SoR actuation / Actions Ledger) + RLS.

Governed, idempotent, reversible write-back to a system of record. Both tables
are tenant-scoped, so they go under the standard RLS policy on Postgres.
Idempotent.

Revision ID: 0009_actuation
Revises: 0008_outcome_records
Create Date: 2026-07-24
"""
from alembic import op

from app.models.actuation import SorObject, ActionRecord
from app.core.rls import rls_enable_statements

revision = "0009_actuation"
down_revision = "0008_outcome_records"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    SorObject.__table__.create(bind=bind, checkfirst=True)
    ActionRecord.__table__.create(bind=bind, checkfirst=True)
    if bind.dialect.name == "postgresql":
        from sqlalchemy import text
        for table in ("sor_objects", "action_records"):
            for stmt in rls_enable_statements(table):
                bind.execute(text(stmt))


def downgrade() -> None:
    ActionRecord.__table__.drop(bind=op.get_bind(), checkfirst=True)
    SorObject.__table__.drop(bind=op.get_bind(), checkfirst=True)
