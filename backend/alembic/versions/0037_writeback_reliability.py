"""Wave 2 write-back reliability: outbound external idempotency key, signal
natural-key dedup, per-connector incremental pull cursor.

Additive + inspector-guarded (SQLite dev uses create_all; this runs on Postgres
prod). The signals unique index is safe to add immediately: existing rows have
external_id NULL and NULLs are distinct, so no collision.

Revision ID: 0037_writeback_reliability
Revises: 0036_wave1_security_p2p
Create Date: 2026-08-14
"""
import sqlalchemy as sa
from alembic import op

revision = "0037_writeback_reliability"
down_revision = "0036_wave1_security_p2p"
branch_labels = None
depends_on = None


def _cols(insp, table):
    return {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    pg = bind.dialect.name == "postgresql"
    tables = set(insp.get_table_names())

    # ── Outbound external idempotency token ───────────────────────────────────
    if "outbound_writes" in tables and "idempotency_key" not in _cols(insp, "outbound_writes"):
        op.add_column("outbound_writes", sa.Column("idempotency_key", sa.String(64), nullable=True))
        # Backfill existing rows with their PK (already unique + stable).
        op.execute("UPDATE outbound_writes SET idempotency_key = id WHERE idempotency_key IS NULL")
        if pg:
            op.alter_column("outbound_writes", "idempotency_key", nullable=False)
        op.create_index("ix_outbound_writes_idempotency_key", "outbound_writes", ["idempotency_key"])

    # ── Signals natural-key dedup (re-sync UPDATEs the twin, no duplicate) ─────
    if "signals" in tables and "external_id" not in _cols(insp, "signals"):
        op.add_column("signals", sa.Column("external_id", sa.String(256), nullable=True))
        op.create_index("uq_signals_natural", "signals",
                        ["tenant_id", "source_type", "external_id"], unique=True)

    # ── Per-connector incremental pull cursor ─────────────────────────────────
    if "connectors" in tables and "sync_cursor" not in _cols(insp, "connectors"):
        op.add_column("connectors", sa.Column("sync_cursor", sa.Text(), nullable=True))


def downgrade() -> None:
    # Additive; safe to leave in place.
    pass
