"""Tie each metered model call to the decision that caused it

Revision ID: c8d2e5f6b312
Revises: b7c1d9e4a201
Create Date: 2026-07-17

CostEvent recorded model_name/tokens/cost/latency but nothing linking a call to
the execution it belonged to. The best "cost per decision" that allowed was
"average cost of this skill, ever" - a different question, and not the one a
buyer asks. execution_id makes the real figure available.

Correlation id, not a foreign key: a gate-blocked action still burns tokens
(the compliance and fairness gates run before Gate 5), so cost rows legitimately
exist for executions that were never persisted.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'c8d2e5f6b312'
down_revision: Union[str, Sequence[str], None] = 'b7c1d9e4a201'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("cost_events"):
        return  # fresh DB: init_db()/create_all will create it with execution_id
    if any(c["name"] == "execution_id" for c in inspector.get_columns("cost_events")):
        return  # already present via create_all
    op.add_column("cost_events", sa.Column("execution_id", sa.String(), nullable=True))
    op.create_index("ix_cost_events_execution_id", "cost_events", ["execution_id"])


def downgrade() -> None:
    op.drop_index("ix_cost_events_execution_id", table_name="cost_events")
    op.drop_column("cost_events", "execution_id")
