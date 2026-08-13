"""Maker-checker on rules: record the maker.

`rules.authored_by` stores who authored a rule (an authenticated human
principal or a system engine like "regulatory_engine"). New rules land
non-executable and become executable only through /rules/{id}/validate, where
the checker - the authenticated principal - must differ from a human maker
(four-eyes). Additive + nullable (existing rows keep NULL = unknown author,
which never blocks validation).

Revision ID: 0033_rule_authored_by
Revises: 0032_unified_provenance_chain
Create Date: 2026-08-14
"""
import sqlalchemy as sa
from alembic import op

revision = "0033_rule_authored_by"
down_revision = "0032_unified_provenance_chain"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "rules" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("rules")}
    if "authored_by" not in cols:
        op.add_column("rules", sa.Column("authored_by", sa.String(128), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "rules" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("rules")}
        if "authored_by" in cols:
            op.drop_column("rules", "authored_by")
