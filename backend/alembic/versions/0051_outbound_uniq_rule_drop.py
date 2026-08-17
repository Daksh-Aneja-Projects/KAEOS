"""outbound idempotency composite unique + drop orphaned rule_embeddings

  * ``outbound_writes``: enforce AT MOST ONE queued write per (tenant_id,
    idempotency_key) so a retried actuation cannot double-meter / double-send.
    Any pre-existing duplicate pairs are collapsed to the lowest id first, else
    the constraint creation fails on a populated table.
  * drop ``rule_embeddings``: fully orphaned after the dead read-path removal
    (a reader, no writer). Safe to run after 0038 built the ANN index.

Additive + inspector-guarded (DEV_MODE create_all pre-builds the current-model
schema — outbound's UNIQUE is already present there, and rule_embeddings is
already absent — so both branches no-op on that path).

Revision ID: 0051_outbound_uniq_rule_drop
Revises: 0050_legal_hold

(revision id kept <=32 chars — alembic_version is VARCHAR(32).)
"""
import sqlalchemy as sa
from alembic import op

revision = "0051_outbound_uniq_rule_drop"
down_revision = "0050_legal_hold"
branch_labels = None
depends_on = None

_UQ = "uq_outbound_idempotency"


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())

    # SQLite cannot ALTER TABLE ADD CONSTRAINT; on the dev/test SQLite path the
    # UNIQUE comes from the model __table_args__ via create_all, so the native
    # constraint DDL is Postgres-only (mirrors 0031's is_pg guard).
    if "outbound_writes" in tables and bind.dialect.name == "postgresql":
        existing = {u["name"] for u in insp.get_unique_constraints("outbound_writes")}
        if _UQ not in existing:
            # Collapse any duplicate (tenant_id, idempotency_key) pairs to the
            # lowest id first, else the constraint fails on a populated table.
            op.execute(sa.text(
                "DELETE FROM outbound_writes WHERE idempotency_key IS NOT NULL AND id NOT IN "
                "(SELECT MIN(id) FROM outbound_writes WHERE idempotency_key IS NOT NULL "
                "GROUP BY tenant_id, idempotency_key)"
            ))
            op.create_unique_constraint(_UQ, "outbound_writes", ["tenant_id", "idempotency_key"])

    # DROP TABLE is supported on SQLite too, so no dialect guard needed here.
    if "rule_embeddings" in tables:
        op.drop_table("rule_embeddings")


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())

    # SQLite cannot ALTER TABLE DROP CONSTRAINT (no batch here); the constraint is
    # only ever created on the real (Postgres) path, and a dev SQLite DB is rebuilt
    # from create_all, so scope the drop to Postgres — mirrors 0031's is_pg guard.
    if "outbound_writes" in tables and bind.dialect.name == "postgresql":
        existing = {u["name"] for u in insp.get_unique_constraints("outbound_writes")}
        if _UQ in existing:
            op.drop_constraint(_UQ, "outbound_writes", type_="unique")
    # rule_embeddings is intentionally NOT recreated (orphaned; nothing wrote it).
