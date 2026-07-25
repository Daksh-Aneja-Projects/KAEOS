"""Add api_keys (DB-backed platform API keys) + RLS.

Replaces the module-global JSON key store so revocation propagates across
workers/replicas. Tenant-scoped: RLS on Postgres. Idempotent.

Revision ID: 0015_api_keys
Revises: 0014_job_queue
Create Date: 2026-07-25
"""
from alembic import op

from app.models.api_key import ApiKey
from app.core.rls import rls_enable_statements

revision = "0015_api_keys"
down_revision = "0014_job_queue"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    ApiKey.__table__.create(bind=bind, checkfirst=True)
    if bind.dialect.name == "postgresql":
        from sqlalchemy import text
        for stmt in rls_enable_statements("api_keys"):
            bind.execute(text(stmt))


def downgrade() -> None:
    ApiKey.__table__.drop(bind=op.get_bind(), checkfirst=True)
