"""Department scope on users (NULL = org-wide).

A department-scoped user (e.g. department='hr') is confined to that
department's operational surface; cross-domain aggregates stay readable.
Idempotent add-column.

Revision ID: 0021_user_department
Revises: 0020_notifications
Create Date: 2026-07-25
"""
import sqlalchemy as sa
from alembic import op

revision = "0021_user_department"
down_revision = "0020_notifications"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    cols = [c["name"] for c in sa.inspect(bind).get_columns("users")]
    if "department" not in cols:
        op.add_column("users", sa.Column("department", sa.String(32), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    cols = [c["name"] for c in sa.inspect(bind).get_columns("users")]
    if "department" in cols:
        op.drop_column("users", "department")
