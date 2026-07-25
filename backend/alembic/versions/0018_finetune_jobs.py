"""Add finetune_jobs (L2 external fine-tune bridge) + RLS.

Tracks external fine-tuning jobs; on completion the bridge auto-triggers a real
ModelEvolutionRun. Tenant-scoped: RLS on Postgres. Idempotent.

Revision ID: 0018_finetune_jobs
Revises: 0017_autonomy_auto_managed
Create Date: 2026-07-25
"""
from alembic import op

from app.models.foundry import FineTuneJob
from app.core.rls import rls_enable_statements

revision = "0018_finetune_jobs"
down_revision = "0017_autonomy_auto_managed"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    FineTuneJob.__table__.create(bind=bind, checkfirst=True)
    if bind.dialect.name == "postgresql":
        from sqlalchemy import text
        for stmt in rls_enable_statements("finetune_jobs"):
            bind.execute(text(stmt))


def downgrade() -> None:
    FineTuneJob.__table__.drop(bind=op.get_bind(), checkfirst=True)
