"""Add sso_connections (enterprise OIDC/SAML SSO config) + RLS.

Per-tenant Identity-Provider connections. Client secret is Fernet-encrypted in
the application layer. Tenant-scoped: RLS on Postgres. Idempotent.

Revision ID: 0013_sso_connections
Revises: 0012_perf_indexes
Create Date: 2026-07-25
"""
from alembic import op

from app.models.sso import SSOConnection
from app.core.rls import rls_enable_statements

revision = "0013_sso_connections"
down_revision = "0012_perf_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    SSOConnection.__table__.create(bind=bind, checkfirst=True)
    if bind.dialect.name == "postgresql":
        from sqlalchemy import text
        for stmt in rls_enable_statements("sso_connections"):
            bind.execute(text(stmt))


def downgrade() -> None:
    SSOConnection.__table__.drop(bind=op.get_bind(), checkfirst=True)
