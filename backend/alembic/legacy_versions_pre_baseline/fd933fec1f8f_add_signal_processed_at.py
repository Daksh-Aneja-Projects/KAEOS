"""add_signal_processed_at

Revision ID: fd933fec1f8f
Revises: a3fffbddea48
Create Date: 2026-07-11 00:13:41.672499

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'fd933fec1f8f'
down_revision: Union[str, Sequence[str], None] = 'a3fffbddea48'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add processed_at column to signals table for PreCog Engine idempotency."""
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table('signals'):
        # Fresh database, init_db()/create_all has not run yet: it will create
        # signals WITH processed_at (the model already has it). Nothing to do.
        return
    if any(c['name'] == 'processed_at' for c in inspector.get_columns('signals')):
        return  # already present via create_all
    # Use batch_alter_table for SQLite compatibility
    with op.batch_alter_table('signals', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.create_index('ix_signals_processed_at', ['processed_at'], unique=False)


def downgrade() -> None:
    """Remove processed_at column from signals table."""
    with op.batch_alter_table('signals', schema=None) as batch_op:
        batch_op.drop_index('ix_signals_processed_at')
        batch_op.drop_column('processed_at')
