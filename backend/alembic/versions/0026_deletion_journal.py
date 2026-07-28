"""Deletion journal: record erasures for backup-restore replay, with RLS.

A restored backup predates an erasure and would resurrect deleted PII. This
append-only journal (no raw PII - employee id + SHA-256 of email only) lets
``privacy_erasure.replay_deletions`` re-apply every erasure after a restore.

Revision ID: 0026_deletion_journal
Revises: 0025_backfill_always_hitl
Create Date: 2026-07-28
"""
from alembic import op

from app.models.settings import DeletionJournal
from app.core.rls import rls_enable_statements

revision = "0026_deletion_journal"
down_revision = "0025_backfill_always_hitl"
branch_labels = None
depends_on = None

_TABLE = "deletion_journal"


def upgrade() -> None:
    bind = op.get_bind()
    DeletionJournal.__table__.create(bind=bind, checkfirst=True)
    if bind.dialect.name == "postgresql":
        from sqlalchemy import text
        for stmt in rls_enable_statements(_TABLE):
            bind.execute(text(stmt))


def downgrade() -> None:
    DeletionJournal.__table__.drop(bind=op.get_bind(), checkfirst=True)
