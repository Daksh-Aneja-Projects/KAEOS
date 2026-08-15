"""Support domain fixes: SupportAgent.avg_csat retyped from a channel enum to
a real numeric CSAT score.

The column was declared `Enum(ChannelType)` - a field named "average CSAT"
typed as EMAIL/CHAT/PHONE/PORTAL - and was never written or read anywhere.
Idempotent: on a fresh install `create_all` already builds it as Numeric per
the current model, so this only fires against a database that still carries
the old enum column.

Revision ID: 0046_support_fixes
Revises: 0044_tenant_branding
Create Date: 2026-08-15
"""
import sqlalchemy as sa
from alembic import op

revision = "0046_support_fixes"
down_revision = "0045_engineering_tables"
branch_labels = None
depends_on = None

_TABLE = "sup_agents"
_COL = "avg_csat"


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if _TABLE not in set(insp.get_table_names()):
        return
    cols = {c["name"]: c for c in insp.get_columns(_TABLE)}
    col = cols.get(_COL)
    if col is not None and isinstance(col["type"], sa.Enum):
        op.drop_column(_TABLE, _COL)
        op.add_column(_TABLE, sa.Column(_COL, sa.Numeric(3, 2), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if _TABLE not in set(insp.get_table_names()):
        return
    cols = {c["name"]: c for c in insp.get_columns(_TABLE)}
    col = cols.get(_COL)
    if col is not None and not isinstance(col["type"], sa.Enum):
        op.drop_column(_TABLE, _COL)
        op.add_column(_TABLE, sa.Column(_COL, sa.Enum(
            "EMAIL", "CHAT", "PHONE", "PORTAL", name="channeltype"), nullable=True))
