"""Notification channels + delivery ledger, with RLS.

Outbound notification delivery (SMTP / Slack / webhook) per tenant; channel
secrets are Fernet-encrypted at rest. Idempotent.

Revision ID: 0020_notifications
Revises: 0019_user_mfa
Create Date: 2026-07-25
"""
from alembic import op

from app.models.notifications import NotificationChannel, NotificationDelivery
from app.core.rls import rls_enable_statements

revision = "0020_notifications"
down_revision = "0019_user_mfa"
branch_labels = None
depends_on = None

_TABLES = ("notification_channels", "notification_deliveries")


def upgrade() -> None:
    bind = op.get_bind()
    NotificationChannel.__table__.create(bind=bind, checkfirst=True)
    NotificationDelivery.__table__.create(bind=bind, checkfirst=True)
    if bind.dialect.name == "postgresql":
        from sqlalchemy import text
        for table in _TABLES:
            for stmt in rls_enable_statements(table):
                bind.execute(text(stmt))


def downgrade() -> None:
    bind = op.get_bind()
    NotificationDelivery.__table__.drop(bind=bind, checkfirst=True)
    NotificationChannel.__table__.drop(bind=bind, checkfirst=True)
