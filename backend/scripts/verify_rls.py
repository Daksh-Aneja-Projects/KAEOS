"""
Prove tenant isolation is enforced by the DATABASE, not by application code.

Runs three checks against Postgres:
  1. With app.tenant_id = tenant A, a tenant B row is invisible - even to a
     deliberately unfiltered `SELECT * FROM rules` (the exact bug shape that
     shipped in GET /search).
  2. With the tenant context set, the caller still sees its own rows.
  3. With NO context set, nothing is visible (fails closed, not open).

The app role must NOT own the tables, because an owner bypasses RLS. This
script reports which role it used so the result cannot be misread.

Usage:
    # DATABASE_URL = the APP role (non-owner). KAEOS_OWNER_DB_URL = owner, used
    # only to plant and clean up the probe rows.
    DATABASE_URL=postgresql+asyncpg://kaeos_app:...@host/kaeos \\
    KAEOS_OWNER_DB_URL=postgresql+asyncpg://kaeos:...@host/kaeos \\
    python scripts/verify_rls.py
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

from app.core.database import engine  # noqa: E402

TENANT_A = "tenant_rls_probe_a"
TENANT_B = "tenant_rls_probe_b"

OWNER_URL = os.environ.get(
    "KAEOS_OWNER_DB_URL",
    "postgresql+asyncpg://kaeos:kaeos_dev@localhost:5432/kaeos",
)


async def main():
    if engine.dialect.name != "postgresql":
        print(f"SKIP: RLS is a Postgres feature; DATABASE_URL is {engine.dialect.name}")
        return 0

    owner_engine = create_async_engine(OWNER_URL)

    async with engine.begin() as conn:
        role = (await conn.execute(text("SELECT current_user"))).scalar()
        owner = (await conn.execute(text(
            "SELECT tableowner FROM pg_tables WHERE tablename='rules'"
        ))).scalar()
        forced = (await conn.execute(text(
            "SELECT relforcerowsecurity FROM pg_class WHERE relname='rules'"
        ))).scalar()
        bypasses = (role == owner) and not forced

    # Plant one row per tenant as the OWNER (owners bypass RLS - that is the
    # designed maintenance path).
    async with owner_engine.begin() as oconn:
        for tid, stmt in [(TENANT_A, "RLSPROBE tenant A private rule"),
                          (TENANT_B, "RLSPROBE tenant B private rule")]:
            await oconn.execute(text("""
                INSERT INTO rules (id, tenant_id, statement, trigger_json, action_json,
                                   confidence_scalar, is_archived, version)
                VALUES (:id, :tid, :st, '{}', '{}', 0.9, false, 1)
                ON CONFLICT (id) DO NOTHING
            """), {"id": f"rlsprobe-{tid}", "tid": tid, "st": stmt})

    results = {}
    async with engine.connect() as conn:
        # 1 + 2: as tenant A, run a deliberately UNFILTERED query
        await conn.execute(text("SELECT set_config('app.tenant_id', :t, false)"), {"t": TENANT_A})
        rows = (await conn.execute(text(
            "SELECT tenant_id FROM rules WHERE statement LIKE 'RLSPROBE%'"
        ))).fetchall()
        seen = {r[0] for r in rows}
        results["sees_own"] = TENANT_A in seen
        results["leaks_other"] = TENANT_B in seen

        # 3: no context at all
        await conn.execute(text("SELECT set_config('app.tenant_id', '', false)"))
        none_rows = (await conn.execute(text(
            "SELECT tenant_id FROM rules WHERE statement LIKE 'RLSPROBE%'"
        ))).fetchall()
        results["unset_context_sees"] = len(none_rows)

    async with owner_engine.begin() as oconn:
        await oconn.execute(text("DELETE FROM rules WHERE statement LIKE 'RLSPROBE%'"))
    await owner_engine.dispose()

    print(f"role={role!r} table_owner={owner!r} force_rls={forced}")
    if bypasses:
        print("\n!! This role OWNS the tables, so Postgres bypasses RLS for it.")
        print("   The policies are installed, but to have them ENFORCED the app")
        print("   must connect as a non-owner role (see docs/RUNBOOK.md).")
        print(f"   Unfiltered query as {TENANT_A} saw: {sorted(seen)}")
        return 0

    ok = results["sees_own"] and not results["leaks_other"] and results["unset_context_sees"] == 0
    print(f"  sees own tenant rows .............. {results['sees_own']}")
    print(f"  leaks other tenant rows ........... {results['leaks_other']}  (must be False)")
    print(f"  rows visible with no context ...... {results['unset_context_sees']}  (must be 0)")
    print("\nRLS ENFORCED" if ok else "\nRLS NOT ENFORCING - investigate")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
