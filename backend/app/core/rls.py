"""
Row-Level Security: tenant isolation enforced by Postgres, not by discipline.

Every tenant-scoped query in this codebase is filtered by a hand-written
`.where(X.tenant_id == tenant_id)`. There are 86 of them across the domain
routers alone, and 175 tables carry a tenant_id. One omission leaks a
customer's data to another customer - and it already happened: `GET /search`
shipped with no tenant filter at all, and `/legal/contracts/{id}/clauses`
returned any contract's text to any caller.

RLS makes that class of bug structurally impossible: Postgres itself refuses
to return rows belonging to another tenant, regardless of what the query says.
The application filters remain (they are good practice and keep SQLite dev
working); RLS is the backstop that does not depend on anyone remembering.

Design
------
* Each transaction binds `app.tenant_id` from the request contextvar. That
  happens in ONE place - the `after_begin` listener in app/core/database.py -
  so it covers sessions opened by service code that never sees a request, and
  transactions opened after a commit.
* Policies compare `tenant_id` to `current_setting('app.tenant_id', true)`.
* An unset context matches NOTHING, so a forgotten binding fails closed.
* Trusted internal work (seeders, migrations, cross-tenant admin reports) runs
  as the table OWNER, which Postgres exempts from policies. The application
  therefore MUST connect as a non-owner role (`kaeos_app`) or the policies are
  installed but inert - see scripts/verify_rls.py, which detects exactly that.

SQLite (local dev) has no RLS; these helpers no-op there.
"""
import logging

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


def is_postgres(session: AsyncSession) -> bool:
    """True when this session speaks Postgres.

    A missing/odd bind is a programming error worth seeing, not something to
    swallow into a silent False - that would quietly disable RLS handling.
    """
    bind = session.bind
    if bind is None:
        raise RuntimeError("session has no bind; cannot determine dialect")
    return bind.dialect.name == "postgresql"


# Tables that are intentionally NOT tenant-scoped (platform-global).
GLOBAL_TABLES = {
    # `users` carries tenant_id, but login must resolve the tenant FROM the
    # user - it cannot already know it. Auth is the one path that reads across
    # tenants by necessity, and it matches on a unique email + password hash.
    "users",
    "alembic_version",
}


def rls_enable_statements(table: str) -> list[str]:
    """The statements that put one table under tenant isolation.

    A LIST, not one blob: asyncpg refuses multiple commands in a single
    execute, so callers must run these one at a time.

    Idempotent - safe to re-run on a table that already has the policy.
    """
    return [
        f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY',
        f'DROP POLICY IF EXISTS tenant_isolation ON "{table}"',
        f'''CREATE POLICY tenant_isolation ON "{table}"
                USING (tenant_id = current_setting('app.tenant_id', true))
                WITH CHECK (tenant_id = current_setting('app.tenant_id', true))''',
    ]


def rls_enable_sql(table: str) -> str:
    """SQL to put one table under tenant isolation (semicolon-joined script).

    For migrations/psql. Application code should use rls_enable_statements().
    """
    return ";\n".join(rls_enable_statements(table)) + ";\n"


# Finds every tenant-scoped table that is NOT fully protected: RLS switched off,
# or switched on but missing the policy (which alone protects nothing).
UNPROTECTED_TENANT_TABLES_SQL = """
SELECT DISTINCT c.table_name
FROM information_schema.columns c
JOIN pg_tables t
  ON t.tablename = c.table_name AND t.schemaname = c.table_schema
WHERE c.table_schema = 'public'
  AND c.column_name = 'tenant_id'
  AND (
    t.rowsecurity = false
    OR NOT EXISTS (
      SELECT 1 FROM pg_policies p
      WHERE p.schemaname = 'public'
        AND p.tablename = t.tablename
        AND p.policyname = 'tenant_isolation'
    )
  )
ORDER BY 1
"""


def rls_disable_sql(table: str) -> str:
    return f"""
DROP POLICY IF EXISTS tenant_isolation ON {table};
ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;
"""
