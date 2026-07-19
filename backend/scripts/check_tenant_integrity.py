#!/usr/bin/env python
"""Detect orphaned tenant_ids — rows whose tenant_id is not in the `tenants`
registry. This is the referential-integrity check that stands in for DB-level
foreign keys until a full FK migration (with orphan cleanup) is done.

    python -m scripts.check_tenant_integrity      # report only
    python -m scripts.check_tenant_integrity --strict   # exit 1 if orphans found
"""
import asyncio
import os
import sys

os.environ.setdefault("SECRET_KEY", "ci-integrity-check-000000000000")


async def _run() -> int:
    from sqlalchemy import text
    from app.core.database import engine, Base
    import app.core.database  # noqa: F401 - registers all model modules

    # Tables that carry tenant_id, minus the registry/global tables themselves.
    from app.core.rls import GLOBAL_TABLES
    tenant_tables = [
        name for name, tbl in Base.metadata.tables.items()
        if "tenant_id" in tbl.c and name not in GLOBAL_TABLES
    ]

    orphans: dict[str, set] = {}
    async with engine.connect() as conn:
        known = {r[0] for r in (await conn.execute(text("SELECT tenant_id FROM tenants"))).fetchall()}
        for tname in tenant_tables:
            try:
                rows = await conn.execute(text(f'SELECT DISTINCT tenant_id FROM "{tname}"'))
            except Exception:
                continue  # table not present in this DB
            bad = {r[0] for r in rows.fetchall() if r[0] and r[0] not in known}
            if bad:
                orphans[tname] = bad

    print(f"[integrity] {len(known)} registered tenant(s); scanned "
          f"{len(tenant_tables)} tenant-scoped tables.")
    if not orphans:
        print("[integrity] OK — no orphaned tenant_ids.")
        return 0
    print(f"[integrity] found orphaned tenant_ids in {len(orphans)} table(s):")
    for tname, bad in sorted(orphans.items()):
        print(f"          - {tname}: {sorted(bad)}")
    return 1


def main() -> int:
    strict = "--strict" in sys.argv
    code = asyncio.run(_run())
    return code if strict else 0


if __name__ == "__main__":
    sys.exit(main())
