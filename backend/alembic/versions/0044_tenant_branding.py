"""White-label tenant branding: one brand row per tenant.

Additive + inspector-guarded; RLS is Postgres-only (SQLite dev builds via
create_all). Chained after the metrics store for a single head.

Revision ID: 0044_tenant_branding
Revises: 0043_metrics_timeseries
Create Date: 2026-08-14
"""
import sqlalchemy as sa
from alembic import op

from app.core.rls import rls_enable_statements

revision = "0044_tenant_branding"
down_revision = "0043_metrics_timeseries"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    pg = bind.dialect.name == "postgresql"
    tables = set(insp.get_table_names())

    if "brand_tenant_branding" not in tables:
        op.create_table(
            "brand_tenant_branding",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), nullable=False, index=True),
            sa.Column("product_name", sa.String(length=80), nullable=False, server_default="KAEOS"),
            sa.Column("primary_color", sa.String(length=7), nullable=False, server_default="#6366f1"),
            sa.Column("accent_color", sa.String(length=7), nullable=False, server_default="#22d3ee"),
            sa.Column("logo_url", sa.String(length=512), nullable=True),
            sa.Column("login_subtitle", sa.String(length=200), nullable=True),
            sa.Column("updated_by", sa.String(length=160), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.UniqueConstraint("tenant_id", name="uq_brand_tenant"),
        )
        if pg:
            for stmt in rls_enable_statements("brand_tenant_branding"):
                op.execute(stmt)


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "brand_tenant_branding" in set(insp.get_table_names()):
        op.drop_table("brand_tenant_branding")
