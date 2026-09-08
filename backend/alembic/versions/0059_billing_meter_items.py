"""Per-outcome-class Stripe metered items

Adds billing_accounts.stripe_meter_items (JSON, nullable): a
{"autonomous": "si_...", "assisted": "si_..."} map, populated only for a
tenant on a per-outcome-class metered subscription. stripe_meter_item_id
(the existing flat single-rate item) is untouched and stays the fallback
for every tenant that never moves to per-class pricing.

Additive, inspector-guarded, idempotent. DEV_MODE's create_all pre-builds
it from the model, so this no-ops there.

Revision ID: 0059_billing_meter_items
Revises: 0058_sso_gateway_audience

(revision id kept <=32 chars - alembic_version is VARCHAR(32).)
"""
import sqlalchemy as sa
from alembic import op

revision = "0059_billing_meter_items"
down_revision = "0058_sso_gateway_audience"
branch_labels = None
depends_on = None

_TABLE = "billing_accounts"
_COL = "stripe_meter_items"


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if _TABLE not in set(insp.get_table_names()):
        return
    if _COL in {c["name"] for c in insp.get_columns(_TABLE)}:
        return
    op.add_column(_TABLE, sa.Column(_COL, sa.JSON(), nullable=True))


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if _TABLE not in set(insp.get_table_names()):
        return
    if _COL in {c["name"] for c in insp.get_columns(_TABLE)}:
        op.drop_column(_TABLE, _COL)
