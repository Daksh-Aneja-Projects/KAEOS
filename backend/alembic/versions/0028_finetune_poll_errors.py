"""finetune_jobs.poll_errors — consecutive provider-poll failure counter.

Lets poll_finetune_jobs dead-letter a job whose provider handle is permanently
broken instead of re-polling it forever. Persisted rather than in-process so the
streak survives a worker restart. Idempotent add-column.

Revision ID: 0028_finetune_poll_errors
Revises: 0027_saml_connection
Create Date: 2026-07-31
"""
import sqlalchemy as sa
from alembic import op

revision = "0028_finetune_poll_errors"
down_revision = "0027_saml_connection"
branch_labels = None
depends_on = None

_TABLE = "finetune_jobs"


def upgrade() -> None:
    bind = op.get_bind()
    cols = [c["name"] for c in sa.inspect(bind).get_columns(_TABLE)]
    if "poll_errors" not in cols:
        op.add_column(_TABLE, sa.Column("poll_errors", sa.Integer(),
                                        nullable=False, server_default="0"))


def downgrade() -> None:
    bind = op.get_bind()
    cols = [c["name"] for c in sa.inspect(bind).get_columns(_TABLE)]
    if "poll_errors" in cols:
        op.drop_column(_TABLE, "poll_errors")
