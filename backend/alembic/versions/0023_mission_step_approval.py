"""Add mission_steps.approved_by / approved_at (persisted HITL approval record).

The executor's hitl_pre_approved flag was derived from step.hitl_required (the
requirement), not from evidence a human approval occurred. These columns are the
source of truth: written only by resolve_hitl_step on approval, read by the
mission engine before a HITL-gated step may execute.

Revision ID: 0023_mission_step_approval
Revises: 0022_sync_engine
Create Date: 2026-07-27
"""
from alembic import op
import sqlalchemy as sa

revision = "0023_mission_step_approval"
down_revision = "0022_sync_engine"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    cols = [c["name"] for c in sa.inspect(bind).get_columns("mission_steps")]
    if "approved_by" not in cols:
        op.add_column("mission_steps", sa.Column("approved_by", sa.String(), nullable=True))
    if "approved_at" not in cols:
        op.add_column("mission_steps", sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    cols = [c["name"] for c in sa.inspect(bind).get_columns("mission_steps")]
    if "approved_at" in cols:
        op.drop_column("mission_steps", "approved_at")
    if "approved_by" in cols:
        op.drop_column("mission_steps", "approved_by")
