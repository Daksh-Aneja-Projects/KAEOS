"""Unified provenance ledger (schema v2): scope + version columns, DB-serialized
appends, and append-only grants.

The one ProvenanceLedger table was written by five incompatible chain_hash
schemes; the verifier false-positived "TAMPERED" on clean data (review P0 #2/#3).
The unified writer (app/services/provenance.py) needs:

- `chain_scope`  - which chain an entry belongs to (rule/skill id or "_tenant")
- `schema_version` - which scheme signed the row (NULL = legacy, reported
  honestly by the verifier rather than "TAMPERED")
- unique (tenant_id, chain_scope, parent_id) - at most ONE child per parent
  per chain, so concurrent appends cannot fork a chain on any worker count
- partial unique (tenant_id, chain_scope) WHERE parent_id IS NULL - at most
  one genesis row per chain
- Postgres only: REVOKE UPDATE/DELETE from the app role (kaeos_app), making
  the ledger append-only at the database layer, not by convention

Existing rows keep NULL scope/version (legacy). Additive + idempotent.

Revision ID: 0032_unified_provenance_chain
Revises: 0031_tenant_scoped_unique_keys
Create Date: 2026-08-13
"""
import logging

import sqlalchemy as sa
from alembic import op

revision = "0032_unified_provenance_chain"
down_revision = "0031_tenant_scoped_unique_keys"
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic")

_TABLE = "provenance_ledger"
_APP_ROLE = "kaeos_app"


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if _TABLE not in insp.get_table_names():
        return

    cols = {c["name"] for c in insp.get_columns(_TABLE)}
    if "chain_scope" not in cols:
        op.add_column(_TABLE, sa.Column("chain_scope", sa.String(64), nullable=True))
    if "schema_version" not in cols:
        op.add_column(_TABLE, sa.Column("schema_version", sa.String(8), nullable=True))

    index_names = {i["name"] for i in insp.get_indexes(_TABLE)}
    if "ix_provenance_ledger_chain_scope" not in index_names:
        op.create_index("ix_provenance_ledger_chain_scope", _TABLE, ["chain_scope"])
    if "uq_prov_chain_parent" not in index_names:
        op.create_index(
            "uq_prov_chain_parent", _TABLE,
            ["tenant_id", "chain_scope", "parent_id"], unique=True,
        )
    if "uq_prov_chain_genesis" not in index_names:
        op.create_index(
            "uq_prov_chain_genesis", _TABLE,
            ["tenant_id", "chain_scope"], unique=True,
            postgresql_where=sa.text("parent_id IS NULL"),
            sqlite_where=sa.text("parent_id IS NULL"),
        )

    # Append-only at the database layer (Postgres). Migrations run as the
    # table owner, so revoking from the app role is allowed; if the role does
    # not exist in this environment (dev), skip without failing the upgrade.
    if bind.dialect.name == "postgresql":
        role_exists = bind.execute(
            sa.text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": _APP_ROLE}
        ).scalar()
        if role_exists:
            op.execute(f"REVOKE UPDATE, DELETE ON {_TABLE} FROM {_APP_ROLE}")
        else:
            logger.info(
                f"[0032] role {_APP_ROLE} not present; skipping append-only REVOKE"
            )


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
    index_names = {i["name"] for i in insp.get_indexes(_TABLE)}
    for ix in ("uq_prov_chain_genesis", "uq_prov_chain_parent",
               "ix_provenance_ledger_chain_scope"):
        if ix in index_names:
            op.drop_index(ix, table_name=_TABLE)
    cols = {c["name"] for c in insp.get_columns(_TABLE)}
    for col in ("schema_version", "chain_scope"):
        if col in cols:
            op.drop_column(_TABLE, col)
