"""legal-hold column on record tables + billing subscription-event cursor

Activates two guards that shipped inert (column-absent no-ops) plus lending SoD:
  * ``on_legal_hold`` (Boolean, default False) on the record/document tables a
    litigation hold realistically targets — makes ``erase_subject`` /
    ``purge_tenant`` / retention preserve held rows (GDPR Art.17(3); FRCP 37(e)).
  * ``billing_accounts.last_subscription_event_at`` (BigInteger) — the
    out-of-order-webhook guard in ``stripe_bridge`` (a stale event cannot
    re-grant a cancelled tenant).
  * ``lnd_credit_policies.updated_by`` (String) — the policy-maker identity that
    feeds LENDING_SOD four-eyes (underwriter must differ from policy maker).

Additive + inspector-guarded (SQLite dev builds via create_all, which already
carries these columns from the models — see 0049_ops_work_orders.py for the same
pattern). Boolean default is ``sa.false()`` (a bare 0/1 breaks a Postgres Boolean).

Revision ID: 0050_legal_hold
Revises: 0049_ops_work_orders
"""
import sqlalchemy as sa
from alembic import op

revision = "0050_legal_hold"
down_revision = "0049_ops_work_orders"
branch_labels = None
depends_on = None

# Record/document tables a legal hold can target (erasure + purge scope).
_HOLD_TABLES = [
    "hr_employees", "hr_candidates", "hr_employee_documents",
    "lnd_loan_applications", "lnd_serviced_loans", "lnd_collection_cases",
    "hlth_encounters", "hlth_consent_records", "hlth_phi_disclosures",
    "sls_contacts", "sls_leads", "sls_reps",
    "fin_vendors", "fin_customers", "fin_invoices", "fin_expense_items",
    "fin_control_tests", "fin_reports",
    "sup_agents", "eng_engineers", "ops_team_members",
    "leg_data_subject_requests", "leg_contracts", "leg_court_filings",
]


def _cols(insp, table):
    return {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())

    for table in _HOLD_TABLES:
        if table in tables and "on_legal_hold" not in _cols(insp, table):
            op.add_column(table, sa.Column(
                "on_legal_hold", sa.Boolean(), nullable=False,
                server_default=sa.false(),
            ))
    if "billing_accounts" in tables and \
            "last_subscription_event_at" not in _cols(insp, "billing_accounts"):
        op.add_column("billing_accounts", sa.Column(
            "last_subscription_event_at", sa.BigInteger(), nullable=True,
        ))
    if "lnd_credit_policies" in tables and \
            "updated_by" not in _cols(insp, "lnd_credit_policies"):
        op.add_column("lnd_credit_policies", sa.Column(
            "updated_by", sa.String(length=160), nullable=True,
        ))


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())

    if "lnd_credit_policies" in tables and \
            "updated_by" in _cols(insp, "lnd_credit_policies"):
        op.drop_column("lnd_credit_policies", "updated_by")
    if "billing_accounts" in tables and \
            "last_subscription_event_at" in _cols(insp, "billing_accounts"):
        op.drop_column("billing_accounts", "last_subscription_event_at")
    for table in _HOLD_TABLES:
        if table in tables and "on_legal_hold" in _cols(insp, table):
            op.drop_column(table, "on_legal_hold")
