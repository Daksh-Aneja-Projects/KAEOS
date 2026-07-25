"""Add user_mfa (TOTP second factor) + RLS.

Per-user MFA enrollment; the TOTP secret is Fernet-encrypted at rest.
Tenant-scoped: RLS on Postgres. Idempotent.

Revision ID: 0019_user_mfa
Revises: 0018_finetune_jobs
Create Date: 2026-07-25
"""
from alembic import op

from app.models.mfa import UserMFA
from app.core.rls import rls_enable_statements

revision = "0019_user_mfa"
down_revision = "0018_finetune_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    UserMFA.__table__.create(bind=bind, checkfirst=True)
    if bind.dialect.name == "postgresql":
        from sqlalchemy import text
        for stmt in rls_enable_statements("user_mfa"):
            bind.execute(text(stmt))


def downgrade() -> None:
    UserMFA.__table__.drop(bind=op.get_bind(), checkfirst=True)
