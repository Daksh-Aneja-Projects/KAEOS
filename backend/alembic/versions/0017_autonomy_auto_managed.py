"""Add autonomy_policies.auto_managed (L5-reverse autonomy governor).

Marks dials the governor manages from the measured safe-autonomy-rate; a human
edit flips it False so the governor never overrides an explicit decision.
Idempotent.

Revision ID: 0017_autonomy_auto_managed
Revises: 0016_mission_step_actuation
Create Date: 2026-07-25
"""
from alembic import op
import sqlalchemy as sa

revision = "0017_autonomy_auto_managed"
down_revision = "0016_mission_step_actuation"
branch_labels = None
depends_on = None

_TABLE = "autonomy_policies"


def upgrade() -> None:
    bind = op.get_bind()
    cols = [c["name"] for c in sa.inspect(bind).get_columns(_TABLE)]
    if "auto_managed" not in cols:
        op.add_column(_TABLE, sa.Column("auto_managed", sa.Boolean(),
                                        nullable=False, server_default=sa.false()))


def downgrade() -> None:
    bind = op.get_bind()
    cols = [c["name"] for c in sa.inspect(bind).get_columns(_TABLE)]
    if "auto_managed" in cols:
        op.drop_column(_TABLE, "auto_managed")
