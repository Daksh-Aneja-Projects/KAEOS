"""Company Brain proposals — self-proposed, human-governed missions

The Brain reflects on operational reality (autonomy-rate decline, cost spikes,
systems-of-record drift, recurring mission failures, knowledge backlog) and
proposes its own missions. A proposal is inert until a human approves it; the
outcome column is stamped from the spawned mission's terminal status so the
brain learns which kinds of proposal are worth making.

Additive, inspector-guarded, idempotent: create brain_proposals if absent.
DEV_MODE's create_all pre-builds it from the model, so this no-ops there.

Revision ID: 0057_brain_proposals
Revises: 0056_legalhold_support_ops

(revision id kept <=32 chars - alembic_version is VARCHAR(32).)
"""
import sqlalchemy as sa
from alembic import op

revision = "0057_brain_proposals"
down_revision = "0056_legalhold_support_ops"
branch_labels = None
depends_on = None

_TABLE = "brain_proposals"


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if _TABLE in set(insp.get_table_names()):
        return
    op.create_table(
        _TABLE,
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("goal", sa.Text(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        # NOT NULL to match the models (non-Optional Mapped[...]); the ORM always
        # supplies these (evidence=[], priority via score, created_at=now), and a
        # new table has no rows needing a backfill default.
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("signal_kind", sa.String(length=32), nullable=False),
        sa.Column("dedup_key", sa.String(length=160), nullable=False),
        sa.Column("priority", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="PENDING"),
        sa.Column("mission_id", sa.String(), nullable=True),
        sa.Column("outcome", sa.String(length=16), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by", sa.String(), nullable=True),
    )
    op.create_index("ix_brain_proposals_tenant_id", _TABLE, ["tenant_id"])
    op.create_index("ix_brain_proposals_created_at", _TABLE, ["created_at"])
    op.create_index("ix_brain_proposals_dedup", _TABLE, ["tenant_id", "dedup_key", "created_at"])
    op.create_index("ix_brain_proposals_status", _TABLE, ["tenant_id", "status"])


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if _TABLE in set(insp.get_table_names()):
        op.drop_table(_TABLE)
