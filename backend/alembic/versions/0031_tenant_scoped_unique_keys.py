"""Tenant-scoped business keys: global unique -> composite (tenant_id, key).

worker_id, emails, invoice/entry/ticket/po/report/finding numbers, control
codes, slugs and skill_id were globally unique, so tenant B could not create
INV-001 (or seed the standard skill catalog) once tenant A had - a cross-
tenant collision and denial-of-service (review P0.5). Loosening a constraint
needs no data migration.

Postgres: drop the single-column unique constraint/index, add the composite.
SQLite (dev): inline UNIQUE cannot be dropped without a table rebuild; the
composite index is still added and the ORM models now declare the composite,
so any recreated dev DB is correct.
# ponytail: legacy inline UNIQUE stays on old SQLite dev DBs (over-strict,
# not wrong); rebuild the table here if a dev DB ever needs two tenants.

Revision ID: 0031_tenant_scoped_unique_keys
Revises: 0030_clear_fabricated_hours_saved
Create Date: 2026-08-13
"""
import sqlalchemy as sa
from alembic import op

revision = "0031_tenant_scoped_unique_keys"
down_revision = "0030_clear_fabricated_hours_saved"
branch_labels = None
depends_on = None

# (table, column, composite unique name)
CONVERSIONS = [
    ("fin_customer_invoices", "invoice_number", "uq_fin_cust_inv_tenant_number"),
    ("fin_audit_findings", "finding_number", "uq_fin_finding_tenant_number"),
    ("fin_sox_controls", "control_id_code", "uq_fin_sox_tenant_code"),
    ("fin_journal_entries", "entry_number", "uq_fin_je_tenant_number"),
    ("fin_expense_reports", "report_number", "uq_fin_exp_tenant_number"),
    ("hr_employees", "worker_id", "uq_hr_emp_tenant_worker"),
    ("hr_employees", "email", "uq_hr_emp_tenant_email"),
    ("leg_team_members", "email", "uq_leg_team_tenant_email"),
    ("ops_team_members", "email", "uq_ops_team_tenant_email"),
    ("ops_department_configs", "department_slug", "uq_ops_dept_tenant_slug"),
    ("ops_purchase_orders", "po_number", "uq_ops_po_tenant_number"),
    ("sls_reps", "email", "uq_sls_rep_tenant_email"),
    ("sup_agents", "email", "uq_sup_agent_tenant_email"),
    ("sup_kb_categories", "slug", "uq_sup_kbcat_tenant_slug"),
    ("sup_tickets", "ticket_number", "uq_sup_ticket_tenant_number"),
    ("skills", "skill_id", "uq_skills_tenant_skill_id"),
]


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())
    is_pg = bind.dialect.name == "postgresql"

    for table, col, uq_name in CONVERSIONS:
        if table not in tables:
            continue
        existing = {c["name"] for c in insp.get_unique_constraints(table)}
        indexes = insp.get_indexes(table)
        index_names = {i["name"] for i in indexes}

        if is_pg:
            for uc in insp.get_unique_constraints(table):
                if uc["column_names"] == [col]:
                    op.drop_constraint(uc["name"], table, type_="unique")
            for ix in indexes:
                if ix.get("unique") and ix["column_names"] == [col]:
                    op.drop_index(ix["name"], table_name=table)

        if uq_name not in existing and uq_name not in index_names:
            op.create_index(uq_name, table, ["tenant_id", col], unique=True)


def downgrade() -> None:
    # Re-tightening to global unique could fail on legitimately duplicated
    # tenant-scoped keys; only the composite is removed.
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())
    for table, _col, uq_name in CONVERSIONS:
        if table not in tables:
            continue
        if uq_name in {i["name"] for i in insp.get_indexes(table)}:
            op.drop_index(uq_name, table_name=table)
