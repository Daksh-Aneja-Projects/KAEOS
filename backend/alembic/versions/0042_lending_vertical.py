"""Banking-lending vertical: applications, underwriting, adverse action, policy.

Backs the app/lending package (ECOA/Reg B, fair-lending, TILA governed).
Additive + inspector-guarded; RLS is Postgres-only (SQLite dev builds via
create_all). Chained after healthcare so there is a single head.

Revision ID: 0042_lending_vertical
Revises: 0041_healthcare_tables
Create Date: 2026-08-14
"""
import sqlalchemy as sa
from alembic import op

from app.core.rls import rls_enable_statements

revision = "0042_lending_vertical"
down_revision = "0041_healthcare_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    pg = bind.dialect.name == "postgresql"
    tables = set(insp.get_table_names())

    if "lnd_loan_applications" not in tables:
        op.create_table(
            "lnd_loan_applications",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), nullable=False, index=True),
            sa.Column("application_number", sa.String(length=32), nullable=False),
            sa.Column("applicant_name", sa.String(length=160), nullable=False),
            sa.Column("applicant_ref", sa.String(length=64), nullable=True),
            sa.Column("product", sa.String(length=48), nullable=False),
            sa.Column("credit_purpose", sa.String(length=24), nullable=False),
            sa.Column("amount", sa.Numeric(18, 2), nullable=False),
            sa.Column("term_months", sa.Integer(), nullable=True),
            sa.Column("credit_score", sa.Integer(), nullable=True),
            sa.Column("annual_income", sa.Numeric(18, 2), nullable=True),
            sa.Column("monthly_debt", sa.Numeric(18, 2), nullable=True),
            sa.Column("dti_ratio", sa.Numeric(9, 4), nullable=True),
            sa.Column("protected_class", sa.JSON(), nullable=True),
            sa.Column("status", sa.String(length=16), nullable=False),
            sa.Column("intake_score", sa.Numeric(9, 4), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.UniqueConstraint("tenant_id", "application_number", name="uq_lnd_app_tenant_number"),
        )

    if "lnd_underwriting_decisions" not in tables:
        op.create_table(
            "lnd_underwriting_decisions",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), nullable=False, index=True),
            sa.Column("application_id", sa.String(), sa.ForeignKey("lnd_loan_applications.id"), nullable=False, index=True),
            sa.Column("decision", sa.String(length=16), nullable=False),
            sa.Column("reasons", sa.JSON(), nullable=True),
            sa.Column("confidence", sa.Numeric(9, 4), nullable=True),
            sa.Column("decided_by", sa.String(length=160), nullable=True),
            sa.Column("decided_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("apr", sa.Numeric(9, 4), nullable=True),
            sa.Column("finance_charge", sa.Numeric(18, 2), nullable=True),
            sa.Column("amount_financed", sa.Numeric(18, 2), nullable=True),
            sa.Column("total_of_payments", sa.Numeric(18, 2), nullable=True),
            sa.Column("gate_status", sa.String(length=32), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )

    if "lnd_adverse_action_notices" not in tables:
        op.create_table(
            "lnd_adverse_action_notices",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), nullable=False, index=True),
            sa.Column("application_id", sa.String(), sa.ForeignKey("lnd_loan_applications.id"), nullable=False, index=True),
            sa.Column("decision_id", sa.String(), sa.ForeignKey("lnd_underwriting_decisions.id"), nullable=True),
            sa.Column("specific_reasons", sa.JSON(), nullable=True),
            sa.Column("body", sa.Text(), nullable=True),
            sa.Column("decision_date", sa.Date(), nullable=True),
            sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("within_30_days", sa.Boolean(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )

    if "lnd_credit_policies" not in tables:
        op.create_table(
            "lnd_credit_policies",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), nullable=False, index=True),
            sa.Column("product", sa.String(length=48), nullable=False),
            sa.Column("min_credit_score", sa.Integer(), nullable=False),
            sa.Column("max_dti_ratio", sa.Numeric(9, 4), nullable=False),
            sa.Column("min_annual_income", sa.Numeric(18, 2), nullable=False),
            sa.Column("max_amount", sa.Numeric(18, 2), nullable=False),
            sa.Column("base_apr", sa.Numeric(9, 4), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.UniqueConstraint("tenant_id", "product", name="uq_lnd_policy_tenant_product"),
        )

    if pg:
        for t in ("lnd_loan_applications", "lnd_underwriting_decisions",
                  "lnd_adverse_action_notices", "lnd_credit_policies"):
            for stmt in rls_enable_statements(t):
                op.execute(stmt)


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())
    for t in ("lnd_adverse_action_notices", "lnd_underwriting_decisions",
              "lnd_credit_policies", "lnd_loan_applications"):
        if t in tables:
            op.drop_table(t)
