"""legal-hold flag on the support + operations litigable estate (H17)

LegalHoldMixin was on the HR / finance / legal / healthcare / lending /
engineering / sales record tables, but the actual litigable records in support
and operations were exempt by omission: sup_tickets (Ticket), and the
ops_purchase_requests / ops_purchase_orders estate (PurchaseRequest /
PurchaseOrder). A destructive action on those could not be BLOCKED by the
LEGAL_HOLD checker, i.e. litigation-hold evasion by omission.

Additive, inspector-guarded, idempotent: add on_legal_hold BOOLEAN NOT NULL
DEFAULT false. DEV_MODE's create_all pre-builds the column from the model, so
each branch no-ops there.

Revision ID: 0056_legalhold_support_ops
Revises: 0055_genuine_fks

(revision id kept <=32 chars - alembic_version is VARCHAR(32).)
"""
import sqlalchemy as sa
from alembic import op

revision = "0056_legalhold_support_ops"
down_revision = "0055_genuine_fks"
branch_labels = None
depends_on = None

_TABLES = ["sup_tickets", "ops_purchase_requests", "ops_purchase_orders"]
_COL = "on_legal_hold"


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    tables = set(insp.get_table_names())
    for table in _TABLES:
        if table not in tables:
            continue
        if _COL in {c["name"] for c in insp.get_columns(table)}:
            continue
        op.add_column(table, sa.Column(
            _COL, sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    tables = set(insp.get_table_names())
    for table in _TABLES:
        if table not in tables:
            continue
        if _COL in {c["name"] for c in insp.get_columns(table)}:
            op.drop_column(table, _COL)
