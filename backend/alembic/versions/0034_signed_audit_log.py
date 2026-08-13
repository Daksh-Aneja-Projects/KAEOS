"""Tamper-evident SecurityAuditLog: per-row HMAC signature + append-only grants.

Each audit row now carries an HMAC-SHA256 `signature` over its canonical
content (app/core/audit.py); edits are detectable by verify_audit_rows, and
deletions surface against the windowed AUDIT_CHECKPOINT entries anchored into
the signed provenance ledger. On Postgres, UPDATE/DELETE on the table are
revoked from the app role - the retention sweep runs on the owner session, so
lawful retention purges are unaffected. Existing rows keep NULL signatures
(legacy, reported honestly).

Revision ID: 0034_signed_audit_log
Revises: 0033_rule_authored_by
Create Date: 2026-08-14
"""
import logging

import sqlalchemy as sa
from alembic import op

revision = "0034_signed_audit_log"
down_revision = "0033_rule_authored_by"
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic")

_TABLE = "security_audit_logs"
_APP_ROLE = "kaeos_app"


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if _TABLE not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns(_TABLE)}
    if "signature" not in cols:
        op.add_column(_TABLE, sa.Column("signature", sa.String(64), nullable=True))
    if bind.dialect.name == "postgresql":
        role_exists = bind.execute(
            sa.text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": _APP_ROLE}
        ).scalar()
        if role_exists:
            op.execute(f"REVOKE UPDATE, DELETE ON {_TABLE} FROM {_APP_ROLE}")
        else:
            logger.info(f"[0034] role {_APP_ROLE} not present; skipping REVOKE")


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if _TABLE not in insp.get_table_names():
        return
    if bind.dialect.name == "postgresql":
        role_exists = bind.execute(
            sa.text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": _APP_ROLE}
        ).scalar()
        if role_exists:
            op.execute(f"GRANT UPDATE, DELETE ON {_TABLE} TO {_APP_ROLE}")
    cols = {c["name"] for c in insp.get_columns(_TABLE)}
    if "signature" in cols:
        op.drop_column(_TABLE, "signature")
