"""Add mission_steps.actuation (L7 closed loop: governed write-back intent).

A human-approved mission step carrying an actuation intent triggers runtime
Gate 5b, turning missions from advisory-only into governed "do". Idempotent.

Revision ID: 0016_mission_step_actuation
Revises: 0015_api_keys
Create Date: 2026-07-25
"""
from alembic import op
import sqlalchemy as sa

revision = "0016_mission_step_actuation"
down_revision = "0015_api_keys"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    cols = [c["name"] for c in sa.inspect(bind).get_columns("mission_steps")]
    if "actuation" not in cols:
        op.add_column("mission_steps", sa.Column("actuation", sa.JSON(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    cols = [c["name"] for c in sa.inspect(bind).get_columns("mission_steps")]
    if "actuation" in cols:
        op.drop_column("mission_steps", "actuation")
