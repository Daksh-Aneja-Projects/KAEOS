"""Add jobs (durable background job queue) + RLS.

Persistent at-least-once job queue that replaces fire-and-forget tasks for the
deployment pipeline. Tenant-scoped: RLS on Postgres. Idempotent.

Revision ID: 0014_job_queue
Revises: 0013_sso_connections
Create Date: 2026-07-25
"""
from alembic import op

from app.models.jobs import Job
from app.core.rls import rls_enable_statements

revision = "0014_job_queue"
down_revision = "0013_sso_connections"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    Job.__table__.create(bind=bind, checkfirst=True)
    if bind.dialect.name == "postgresql":
        from sqlalchemy import text
        for stmt in rls_enable_statements("jobs"):
            bind.execute(text(stmt))


def downgrade() -> None:
    Job.__table__.drop(bind=op.get_bind(), checkfirst=True)
