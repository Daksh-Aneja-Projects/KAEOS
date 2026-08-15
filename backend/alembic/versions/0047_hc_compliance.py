"""Healthcare compliance reporting: persisted HIPAA / 42 CFR Part 2 compliance
reports and violations, mirroring HR's ComplianceReport/ComplianceViolation
shape.

Additive + inspector-guarded; RLS is Postgres-only (SQLite dev builds via
create_all). String status/framework columns (no native DB enum), matching
every status column elsewhere in this codebase.

Revision ID: 0047_hc_compliance
Revises: 0044_tenant_branding
Create Date: 2026-08-15
"""
import sqlalchemy as sa
from alembic import op

from app.core.rls import rls_enable_statements

revision = "0047_hc_compliance"
down_revision = "0046_support_fixes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    pg = bind.dialect.name == "postgresql"
    tables = set(insp.get_table_names())

    if "hlth_compliance_reports" not in tables:
        op.create_table(
            "hlth_compliance_reports",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), nullable=False, index=True),
            sa.Column("framework", sa.String(length=32), nullable=False),
            sa.Column("report_name", sa.String(length=256), nullable=False),
            sa.Column("period_year", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="GENERATED"),
            sa.Column("data", sa.JSON(), nullable=False),
            sa.Column("generated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        )
        if pg:
            for stmt in rls_enable_statements("hlth_compliance_reports"):
                op.execute(stmt)

    if "hlth_compliance_violations" not in tables:
        op.create_table(
            "hlth_compliance_violations",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), nullable=False, index=True),
            sa.Column("framework", sa.String(length=64), nullable=False),
            sa.Column("severity", sa.String(length=32), nullable=False),
            sa.Column("description", sa.String(length=512), nullable=False),
            sa.Column("context", sa.JSON(), nullable=True),
            sa.Column("actor_id", sa.String(), nullable=True),
            sa.Column("resolved", sa.Boolean(), server_default=sa.false()),
            sa.Column("resolution_notes", sa.String(length=512), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        if pg:
            for stmt in rls_enable_statements("hlth_compliance_violations"):
                op.execute(stmt)


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())
    for t in ("hlth_compliance_violations", "hlth_compliance_reports"):
        if t in tables:
            op.drop_table(t)
