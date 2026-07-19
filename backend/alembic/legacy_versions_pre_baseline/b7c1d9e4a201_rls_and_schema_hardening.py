"""Tenant RLS + schema hardening (chain_hash width, gate-time FK removal)

Revision ID: b7c1d9e4a201
Revises: fd933fec1f8f
Create Date: 2026-07-17

Everything here was found by running the stack on real Postgres. SQLite (the
dev default) does not enforce foreign keys, ignores VARCHAR lengths, and has
no row-level security - so all of it passed silently in development.

1. chain_hash VARCHAR(64) -> VARCHAR(128)
   The quantum ledger writes sha3_512 (128 hex chars) into the same column the
   standard chain uses for sha256 (64). Postgres raises
   StringDataRightTruncationError; SQLite truncated quietly, corrupting the
   hash chain that the whole provenance guarantee rests on.

2. Drop three foreign keys on gate-time audit writers
   fairness_audit_logs.execution_id, debate_transcripts.execution_id and
   provenance_ledger.rule_id are CORRELATION ids, not references:
     - Gates 2 and 4 write their audit rows BEFORE Gate 5 creates the
       SkillExecution row (and a blocked action never creates one at all).
     - provenance_ledger.rule_id is polymorphic: it holds rule ids for rule
       events and skill ids for AGENT_EXECUTION events.
   With the FKs in place, every gated HR screening 500'd on Postgres.

3. Row-Level Security on every tenant-scoped table
   Tenant isolation was enforced only by hand-written .where() clauses. One
   omission leaks a customer's data - and one already had (GET /search had no
   filter at all). Policies compare tenant_id to current_setting('app.tenant_id'),
   which the request session sets. An unset context matches nothing: fails closed.

   NOTE: the table owner bypasses RLS by design. Run the application as a
   non-owner role (see kaeos_app below) in production so the policies apply;
   migrations and seeders continue to run as the owner.
"""
import os
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'b7c1d9e4a201'
down_revision: Union[str, Sequence[str], None] = 'fd933fec1f8f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Carries tenant_id but must be readable across tenants (login resolves the
# tenant FROM the user, so it cannot already know it).
RLS_EXEMPT = {"users", "alembic_version"}


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return  # SQLite dev: no RLS, no VARCHAR enforcement, nothing to do

    conn = op.get_bind()

    # 1. widen the hash column
    op.alter_column(
        "provenance_ledger", "chain_hash",
        existing_type=sa.String(64), type_=sa.String(128), existing_nullable=True,
    )

    # 2. drop the gate-time FKs (names are Postgres defaults)
    for table, constraint in [
        ("fairness_audit_logs", "fairness_audit_logs_execution_id_fkey"),
        ("debate_transcripts", "debate_transcripts_execution_id_fkey"),
        ("provenance_ledger", "provenance_ledger_rule_id_fkey"),
    ]:
        conn.execute(sa.text(f'ALTER TABLE {table} DROP CONSTRAINT IF EXISTS "{constraint}"'))

    # 3. RLS on every table that has a tenant_id
    tables = [r[0] for r in conn.execute(sa.text("""
        SELECT table_name FROM information_schema.columns
        WHERE table_schema = 'public' AND column_name = 'tenant_id'
        ORDER BY table_name
    """)).fetchall()]

    for table in tables:
        if table in RLS_EXEMPT:
            continue
        conn.execute(sa.text(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY'))
        conn.execute(sa.text(f'DROP POLICY IF EXISTS tenant_isolation ON "{table}"'))
        conn.execute(sa.text(f"""
            CREATE POLICY tenant_isolation ON "{table}"
                USING (tenant_id = current_setting('app.tenant_id', true))
                WITH CHECK (tenant_id = current_setting('app.tenant_id', true))
        """))

    # 4. The application role must NOT own the tables.
    #
    # Postgres exempts a table's owner from its policies, so if the app keeps
    # connecting as the owner the policies above are installed but inert - a
    # false sense of security, which is worse than none. `kaeos_app` is a
    # plain LOGIN role with DML rights and no ownership: RLS applies to it.
    # Migrations and seeders continue to run as the owner and bypass RLS.
    app_pw = os.environ.get("KAEOS_APP_DB_PASSWORD", "kaeos_app_dev")
    conn.execute(sa.text(f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'kaeos_app') THEN
                CREATE ROLE kaeos_app LOGIN PASSWORD '{app_pw}';
            END IF;
        END
        $$;
    """))
    conn.execute(sa.text("GRANT USAGE ON SCHEMA public TO kaeos_app"))
    conn.execute(sa.text(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO kaeos_app"))
    conn.execute(sa.text("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO kaeos_app"))
    # ...and for tables created later
    conn.execute(sa.text("""
        ALTER DEFAULT PRIVILEGES IN SCHEMA public
        GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO kaeos_app
    """))


def downgrade() -> None:
    if not _is_postgres():
        return
    conn = op.get_bind()

    tables = [r[0] for r in conn.execute(sa.text("""
        SELECT table_name FROM information_schema.columns
        WHERE table_schema = 'public' AND column_name = 'tenant_id'
    """)).fetchall()]
    for table in tables:
        if table in RLS_EXEMPT:
            continue
        conn.execute(sa.text(f'DROP POLICY IF EXISTS tenant_isolation ON "{table}"'))
        conn.execute(sa.text(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY'))

    op.alter_column(
        "provenance_ledger", "chain_hash",
        existing_type=sa.String(128), type_=sa.String(64), existing_nullable=True,
    )
    # The dropped FKs are deliberately NOT recreated: they were wrong (see the
    # module docstring). Recreating them would re-break every gated action.
