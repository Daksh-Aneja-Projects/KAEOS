"""model_evolution_runs.prompt_hash — reproducibility stamp for an eval run.

Records the sha256 of the concatenated held-out eval prompts a run scored
against, so two runs of the same deterministic eval slice are comparable and a
scoring change is attributable to the model rather than a shifted prompt set.
Additive + nullable, so it is safe on existing rows. Idempotent add-column.

Revision ID: 0029_model_evolution_prompt_hash
Revises: 0028_finetune_poll_errors
Create Date: 2026-08-01
"""
import sqlalchemy as sa
from alembic import op

revision = "0029_model_evolution_prompt_hash"
down_revision = "0028_finetune_poll_errors"
branch_labels = None
depends_on = None

_TABLE = "model_evolution_runs"


def upgrade() -> None:
    bind = op.get_bind()
    cols = [c["name"] for c in sa.inspect(bind).get_columns(_TABLE)]
    if "prompt_hash" not in cols:
        op.add_column(_TABLE, sa.Column("prompt_hash", sa.String(length=64),
                                        nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    cols = [c["name"] for c in sa.inspect(bind).get_columns(_TABLE)]
    if "prompt_hash" in cols:
        op.drop_column(_TABLE, "prompt_hash")
