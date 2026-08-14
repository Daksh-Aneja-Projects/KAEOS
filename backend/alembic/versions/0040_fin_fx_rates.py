"""Multi-currency GL: FX rate table + per-line base-currency amount.

Adds `fin_fx_rates` (tenant base-currency exchange rates that
`post_journal_entry` converts every foreign line by) and the
`fin_journal_lines.amount_in_base` column that stores the FX-converted
magnitude used by all GL reporting. Additive + inspector-guarded; RLS on the
new table is Postgres-only. SQLite dev builds the table from the ORM via
create_all, so this is a no-op there.

Revision ID: 0040_fin_fx_rates
Revises: 0039_mission_money_tenant_rls
Create Date: 2026-08-14
"""
import sqlalchemy as sa
from alembic import op

from app.core.rls import rls_enable_statements

revision = "0040_fin_fx_rates"
down_revision = "0039_mission_money_tenant_rls"
branch_labels = None
depends_on = None


def _cols(insp, t: str) -> set[str]:
    return {c["name"] for c in insp.get_columns(t)}


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    pg = bind.dialect.name == "postgresql"
    tables = set(insp.get_table_names())

    # 1. amount_in_base on the existing journal-line table (additive, nullable).
    if "fin_journal_lines" in tables and "amount_in_base" not in _cols(insp, "fin_journal_lines"):
        op.add_column(
            "fin_journal_lines",
            sa.Column("amount_in_base", sa.Numeric(18, 2), nullable=True),
        )

    # 2. fin_fx_rates.
    if "fin_fx_rates" not in tables:
        op.create_table(
            "fin_fx_rates",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), nullable=False, index=True),
            sa.Column("currency", sa.String(length=3), nullable=False),
            sa.Column("base_currency", sa.String(length=3), nullable=False, server_default="USD"),
            sa.Column("rate", sa.Numeric(18, 8), nullable=False),
            sa.Column("as_of", sa.Date(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.UniqueConstraint("tenant_id", "currency", "as_of",
                                name="uq_fin_fx_tenant_ccy_asof"),
        )
        if pg:
            for stmt in rls_enable_statements("fin_fx_rates"):
                op.execute(stmt)


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())
    if "fin_fx_rates" in tables:
        op.drop_table("fin_fx_rates")
    if "fin_journal_lines" in tables and "amount_in_base" in _cols(insp, "fin_journal_lines"):
        op.drop_column("fin_journal_lines", "amount_in_base")
