"""Fiscal period lock: close a period to stop back-dated postings.

`fin_fiscal_periods` records a tenant's closed (or reopened) accounting
periods. Absence of a row means OPEN, so months need not be pre-created; only
an explicit CLOSED row blocks `post_journal_entry` from booking into that
month. Closing is a reporting control, not a data migration.

Revision ID: 0035_fiscal_period_lock
Revises: 0034_signed_audit_log
Create Date: 2026-08-14
"""
import sqlalchemy as sa
from alembic import op

revision = "0035_fiscal_period_lock"
down_revision = "0034_signed_audit_log"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "fin_fiscal_periods" in insp.get_table_names():
        return
    op.create_table(
        "fin_fiscal_periods",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False, index=True),
        sa.Column("fiscal_year", sa.Integer(), nullable=False),
        sa.Column("fiscal_period", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="OPEN"),
        sa.Column("closed_by", sa.String(), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.String(length=256), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "fiscal_year", "fiscal_period",
                            name="uq_fin_period_tenant_year_period"),
    )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "fin_fiscal_periods" in insp.get_table_names():
        op.drop_table("fin_fiscal_periods")
