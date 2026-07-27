"""Add skills.always_hitl (explicit high-consequence marker).

The always-route-to-a-human guarantee for payments, terminations and contract
execution previously depended on substring matching over tags and skill names -
a rename silently made a skill autonomous. The explicit flag is authoritative;
tag inference remains only as an escalate-only fallback
(app/services/consequence.py).

Revision ID: 0024_skill_always_hitl
Revises: 0023_mission_step_approval
Create Date: 2026-07-27
"""
from alembic import op
import sqlalchemy as sa

revision = "0024_skill_always_hitl"
down_revision = "0023_mission_step_approval"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    cols = [c["name"] for c in sa.inspect(bind).get_columns("skills")]
    if "always_hitl" not in cols:
        op.add_column(
            "skills",
            sa.Column("always_hitl", sa.Boolean(), nullable=False, server_default=sa.false()),
        )


def downgrade() -> None:
    bind = op.get_bind()
    cols = [c["name"] for c in sa.inspect(bind).get_columns("skills")]
    if "always_hitl" in cols:
        op.drop_column("skills", "always_hitl")
