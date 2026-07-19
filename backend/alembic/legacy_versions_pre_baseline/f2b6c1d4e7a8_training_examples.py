"""Training examples table (AI Foundry, Phase 2)

Revision ID: f2b6c1d4e7a8
Revises: e1a4b8c2f9d3
Create Date: 2026-07-18

KAEOS v2 - Enterprise AI Foundry. This is the first Phase-2 (Learning
Intelligence) table: a curated training dataset mined from the platform's
governed SkillExecution history. It carries tenant_id and is not a global
table, so it goes under the same tenant_isolation RLS policy as every other
tenant table - one enterprise's training data is never visible to another.

Idempotent: skips creation if the table already exists (the SQLAlchemy
create_all path may have made it first in dev).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f2b6c1d4e7a8"
down_revision: Union[str, Sequence[str], None] = "e1a4b8c2f9d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if "training_examples" not in inspector.get_table_names():
        op.create_table(
            "training_examples",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), nullable=False),
            sa.Column("domain", sa.String(length=32), nullable=True),
            sa.Column("instruction", sa.Text(), nullable=False),
            sa.Column("context", sa.JSON(), nullable=True),
            sa.Column("ideal_answer", sa.Text(), nullable=True),
            sa.Column("reasoning", sa.JSON(), nullable=True),
            sa.Column("evaluation_label", sa.String(length=24), nullable=True),
            sa.Column("quality_score", sa.Float(), nullable=True),
            sa.Column("human_verified", sa.Boolean(), nullable=True),
            sa.Column("source", sa.String(length=24), nullable=True),
            sa.Column("source_execution_id", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        op.create_index("ix_training_examples_tenant_id", "training_examples", ["tenant_id"])
        op.create_index("ix_training_examples_domain", "training_examples", ["domain"])
        op.create_index("ix_training_examples_evaluation_label", "training_examples", ["evaluation_label"])
        op.create_index("ix_training_examples_source_execution_id", "training_examples", ["source_execution_id"])
        op.create_index("ix_training_examples_created_at", "training_examples", ["created_at"])

    if conn.dialect.name == "postgresql":
        op.execute("ALTER TABLE training_examples ENABLE ROW LEVEL SECURITY")
        op.execute("DROP POLICY IF EXISTS tenant_isolation ON training_examples")
        op.execute(
            """
            CREATE POLICY tenant_isolation ON training_examples
                USING (tenant_id = current_setting('app.tenant_id', true))
                WITH CHECK (tenant_id = current_setting('app.tenant_id', true))
            """
        )


def downgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name == "postgresql":
        op.execute("DROP POLICY IF EXISTS tenant_isolation ON training_examples")
    op.drop_table("training_examples")
