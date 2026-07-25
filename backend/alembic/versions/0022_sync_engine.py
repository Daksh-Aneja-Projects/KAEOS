"""Bidirectional sync: ledger + outbound write-back queue, with RLS.

Revision ID: 0022_sync_engine
Revises: 0021_user_department
Create Date: 2026-07-25
"""
from alembic import op

from app.models.sync import SyncLedger, OutboundWrite
from app.core.rls import rls_enable_statements

revision = "0022_sync_engine"
down_revision = "0021_user_department"
branch_labels = None
depends_on = None

_TABLES = ("sync_ledger", "outbound_writes")


def upgrade() -> None:
    bind = op.get_bind()
    SyncLedger.__table__.create(bind=bind, checkfirst=True)
    OutboundWrite.__table__.create(bind=bind, checkfirst=True)
    if bind.dialect.name == "postgresql":
        from sqlalchemy import text
        for table in _TABLES:
            for stmt in rls_enable_statements(table):
                bind.execute(text(stmt))


def downgrade() -> None:
    bind = op.get_bind()
    OutboundWrite.__table__.drop(bind=op.get_bind(), checkfirst=True)
    SyncLedger.__table__.drop(bind=bind, checkfirst=True)
