"""Loan servicing + collections: serviced loans (payment schedule, delinquency)
and collection cases (FDCPA-governed contact log).

Backs app/lending/models/servicing.py. FDCPA was advertised in
compliance_frameworks with a full checker (app/compliance/checkers/lending.py)
but nothing built the 'collection' context it reads - this is that feature.
Additive + inspector-guarded; RLS is Postgres-only (SQLite dev builds via
create_all).

Revision ID: 0048_loan_servicing
Revises: 0047_hc_compliance
Create Date: 2026-08-15
"""
import sqlalchemy as sa
from alembic import op

from app.core.rls import rls_enable_statements

revision = "0048_loan_servicing"
down_revision = "0047_hc_compliance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    pg = bind.dialect.name == "postgresql"
    tables = set(insp.get_table_names())

    if "lnd_serviced_loans" not in tables:
        op.create_table(
            "lnd_serviced_loans",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), nullable=False, index=True),
            sa.Column("application_id", sa.String(), sa.ForeignKey("lnd_loan_applications.id"), nullable=True, index=True),
            sa.Column("loan_number", sa.String(length=32), nullable=False),
            sa.Column("product", sa.String(length=48), nullable=False),
            sa.Column("borrower_name", sa.String(length=160), nullable=False),
            sa.Column("principal", sa.Numeric(18, 2), nullable=False),
            sa.Column("outstanding_principal", sa.Numeric(18, 2), nullable=False),
            sa.Column("apr", sa.Numeric(9, 4), nullable=False),
            sa.Column("term_months", sa.Integer(), nullable=False),
            sa.Column("monthly_payment", sa.Numeric(18, 2), nullable=False),
            sa.Column("next_due_date", sa.Date(), nullable=True),
            sa.Column("last_payment_date", sa.Date(), nullable=True),
            sa.Column("last_payment_amount", sa.Numeric(18, 2), nullable=True),
            sa.Column("payments_made", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("days_past_due", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("status", sa.String(length=16), nullable=False),
            sa.Column("payment_schedule", sa.JSON(), nullable=True),
            sa.Column("funded_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.UniqueConstraint("tenant_id", "loan_number", name="uq_lnd_serviced_loan_tenant_number"),
        )

    if "lnd_collection_cases" not in tables:
        op.create_table(
            "lnd_collection_cases",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), nullable=False, index=True),
            sa.Column("serviced_loan_id", sa.String(), sa.ForeignKey("lnd_serviced_loans.id"), nullable=False, index=True),
            sa.Column("status", sa.String(length=16), nullable=False),
            sa.Column("delinquency_bucket", sa.String(length=16), nullable=False),
            sa.Column("validation_notice_sent", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("validation_notice_sent_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("contact_log", sa.JSON(), nullable=True),
            sa.Column("last_contact_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("opened_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )

    if pg:
        for t in ("lnd_serviced_loans", "lnd_collection_cases"):
            for stmt in rls_enable_statements(t):
                op.execute(stmt)


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())
    for t in ("lnd_collection_cases", "lnd_serviced_loans"):
        if t in tables:
            op.drop_table(t)
