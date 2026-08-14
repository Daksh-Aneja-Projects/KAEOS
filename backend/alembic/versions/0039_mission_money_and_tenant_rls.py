"""Wave 4 correctness: mission money Float -> exact Numeric; tenant_id + RLS on
confidence_history and rule_guardrails.

Additive + inspector-guarded. The Numeric TYPE change and RLS are Postgres-only
(SQLite dev builds these from the ORM via create_all).

Revision ID: 0039_mission_money_and_tenant_rls
Revises: 0038_entitlements_and_rag_ann
Create Date: 2026-08-14
"""
import sqlalchemy as sa
from alembic import op

from app.core.rls import rls_enable_statements

revision = "0039_mission_money_tenant_rls"  # <=32 chars (alembic_version VARCHAR(32); Postgres-safe)
down_revision = "0038_entitlements_and_rag_ann"
branch_labels = None
depends_on = None


def _cols(insp, t):
    return {c["name"] for c in insp.get_columns(t)}


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    pg = bind.dialect.name == "postgresql"
    tables = set(insp.get_table_names())

    # ── Mission money: Float -> exact Numeric(18,6) (Postgres coerces existing
    # double-precision values). SQLite already has the ORM Numeric via create_all.
    if pg:
        if "missions" in tables:
            op.execute("ALTER TABLE missions ALTER COLUMN budget_usd TYPE NUMERIC(18,6)")
            op.execute("ALTER TABLE missions ALTER COLUMN spent_usd TYPE NUMERIC(18,6)")
            op.execute("ALTER TABLE missions ALTER COLUMN spent_usd SET DEFAULT 0")
        if "mission_steps" in tables:
            op.execute("ALTER TABLE mission_steps ALTER COLUMN cost_usd TYPE NUMERIC(18,6)")
            op.execute("ALTER TABLE mission_steps ALTER COLUMN cost_usd SET DEFAULT 0")

    # ── tenant_id + RLS on genuinely tenant-scoped child tables ────────────────
    for tbl, parent_fk in (("confidence_history", "rule_id"), ("rule_guardrails", "rule_id")):
        if tbl in tables and "tenant_id" not in _cols(insp, tbl):
            op.add_column(tbl, sa.Column("tenant_id", sa.String(), nullable=True))
            op.execute(f"UPDATE {tbl} c SET tenant_id = r.tenant_id "
                       f"FROM rules r WHERE c.{parent_fk} = r.id AND c.tenant_id IS NULL")
            op.create_index(f"ix_{tbl}_tenant_id", tbl, ["tenant_id"])
            if pg:
                for stmt in rls_enable_statements(tbl):
                    op.execute(stmt)
    # domain_packs + marketplace_templates carry no tenant_id (shared catalogs);
    # they are declared GLOBAL in app.core.rls GLOBAL_TABLES, so the RLS sweep
    # correctly skips them - no schema change needed here.


def downgrade() -> None:
    pass
