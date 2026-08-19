"""Differential row-set equivalence harness for the ten department seeders.

Proves the seed-scaffold consolidation (M1.4: one `seed_tenant(db, tenant)`
contract, shared `new_id` / `already_seeded` / `run_standalone` in
app/core/domain_seed.py) changed no seeded DATA, by RUNNING both versions
rather than reading them - the same technique that proved the gated_runner
consolidation (see scripts/diff_refactor_equivalence.py).

For each department it runs the PRE-refactor module and the current one against
their own throwaway SQLite database, under an identical deterministic
environment:

  * uuid.uuid4  -> a counter, so `new_id()`/`_id()` produce the same sequence
  * random      -> reseeded to a fixed value before each run
  * datetime.now / date.today -> frozen to one instant, injected into the
    module's own namespace (both versions import these by name)

then dumps every non-empty table and compares the two dumps row for row.
It also runs each seeder TWICE to prove the shared idempotency guard still
no-ops a second run, and compares that dump too.

Usage:
    mkdir -p /tmp/old_seeds
    for d in hr finance sales support legal engineering operations \
             healthcare procurement lending; do
      git show <PRE_REFACTOR_REF>:backend/app/$d/seed.py > /tmp/old_seeds/$d.py
    done
    cd backend && python scripts/diff_seed_equivalence.py /tmp/old_seeds

Exits non-zero and prints the first differing table/row when any department
diverges.
"""
from __future__ import annotations

import asyncio
import datetime as _dt
import importlib.util
import os
import random
import sqlite3
import sys
import tempfile
import uuid

sys.path.insert(0, os.path.abspath("."))
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

OLD_DIR = sys.argv[1]
TENANT = "tenant_acme"

# Operations' seed() chains into Procurement, so they share a database and are
# compared as one unit; procurement is also compared standalone.
DEPARTMENTS = [
    "hr", "finance", "sales", "support", "legal",
    "engineering", "operations", "healthcare", "procurement", "lending",
]

FROZEN = _dt.datetime(2026, 3, 17, 11, 22, 33, tzinfo=_dt.timezone.utc)


class _FrozenDatetime(_dt.datetime):
    @classmethod
    def now(cls, tz=None):
        return FROZEN if tz else FROZEN.replace(tzinfo=None)

    @classmethod
    def utcnow(cls):
        return FROZEN.replace(tzinfo=None)

    @classmethod
    def today(cls):
        return FROZEN.replace(tzinfo=None)


class _FrozenDate(_dt.date):
    @classmethod
    def today(cls):
        return FROZEN.date()


def _determinize(mod) -> None:
    """Freeze the clock inside one module's namespace."""
    for name, frozen in ((("datetime", _dt.datetime), _FrozenDatetime),
                         (("date", _dt.date), _FrozenDate)):
        attr, real = name
        if getattr(mod, attr, None) is real:
            setattr(mod, attr, frozen)


def _determinize_all() -> None:
    """Freeze the clock across every loaded app module. Seeders call into real
    services (finance's post_journal_entry stamps provenance_ledger with its own
    datetime.now()), so freezing only the seed module leaves those rows - and
    the hashes derived from them - differing run to run for reasons that have
    nothing to do with the refactor.
    """
    for name, mod in list(sys.modules.items()):
        if (name.startswith("app.") or name.startswith("_old_")) and mod is not None:
            _determinize(mod)


_counter = 0


def _fake_uuid4():
    global _counter
    _counter += 1
    return uuid.UUID(int=_counter)


uuid.uuid4 = _fake_uuid4   # both `_id()` and `new_id()` route through this

# SQLite renders a `server_default=func.now()` column as second-precision
# (2026-08-19 04:00:25) and a Python-supplied datetime as microsecond-precision
# (2026-02-26 11:22:33.000000). Only the former is the database's own clock,
# which no freeze can reach, so mask exactly that shape - seeder-supplied
# timestamps keep their real values and are still compared.
_DB_CLOCK = __import__("re").compile(r"'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}'")


def load_old(dept: str):
    path = os.path.join(OLD_DIR, f"{dept}.py")
    spec = importlib.util.spec_from_file_location(f"_old_{dept}_seed", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def load_new(dept: str):
    import importlib
    return importlib.import_module(f"app.{dept}.seed")


async def run_seed(mod, db_path: str, chained=None) -> None:
    """Point `mod` at its own SQLite file and run seed() twice."""
    from app.models.domain import Base

    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    for m in (mod,) + tuple(chained or ()):
        m.async_engine = engine
        m.AsyncSessionLocal = factory
    _determinize_all()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        global _counter
        _counter = 0
        random.seed(4242)
        _determinize_all()
        await mod.seed()
        # Second run: the idempotency guard must make it a no-op.
        _counter = 100000
        random.seed(99)
        _determinize_all()
        await mod.seed()
    finally:
        await engine.dispose()


def dump(db_path: str) -> dict[str, list[tuple]]:
    con = sqlite3.connect(db_path)
    tables = [r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    out = {}
    for t in tables:
        rows = con.execute(f'SELECT * FROM "{t}"').fetchall()
        if rows:
            cols = [d[0] for d in con.execute(f'SELECT * FROM "{t}" LIMIT 1').description]
            out[t] = [cols] + sorted(_DB_CLOCK.sub("'<db_now>'", repr(r)) for r in rows)
    con.close()
    return out


def compare(dept: str, old: dict, new: dict) -> list[str]:
    diffs = []
    for t in sorted(set(old) | set(new)):
        if t not in new:
            diffs.append(f"{dept}: table {t} written by OLD only ({len(old[t]) - 1} rows)")
        elif t not in old:
            diffs.append(f"{dept}: table {t} written by NEW only ({len(new[t]) - 1} rows)")
        elif old[t] != new[t]:
            o, n = old[t], new[t]
            if len(o) != len(n):
                diffs.append(f"{dept}: table {t} row count {len(o) - 1} -> {len(n) - 1}")
            else:
                first = next(i for i in range(len(o)) if o[i] != n[i])
                diffs.append(f"{dept}: table {t} row {first} differs\n"
                             f"    OLD {o[first]}\n    NEW {n[first]}")
    return diffs


def main() -> int:
    # Import the whole app up front so _determinize_all() reaches services the
    # seeders only import lazily (finance's GL provenance writer among them) -
    # otherwise the first run stamps a real clock and the second a frozen one.
    import app.main  # noqa: F401
    tmp = tempfile.mkdtemp(prefix="seed_equiv_")
    failures, checked = [], []
    for dept in DEPARTMENTS:
        old_mod, new_mod = load_old(dept), load_new(dept)
        # Old operations chains into app.procurement.seed via sys.modules; make
        # sure the OLD run picks the OLD procurement.
        old_chain = new_chain = ()
        if dept == "operations":
            new_proc = load_new("procurement")   # grab it BEFORE shadowing
            old_proc = load_old("procurement")
            sys.modules["app.procurement.seed"] = old_proc
            old_chain, new_chain = (old_proc,), (new_proc,)
        try:
            old_db = os.path.join(tmp, f"{dept}_old.db")
            asyncio.run(run_seed(old_mod, old_db, old_chain))
        finally:
            if dept == "operations":
                sys.modules["app.procurement.seed"] = new_proc
        new_db = os.path.join(tmp, f"{dept}_new.db")
        asyncio.run(run_seed(new_mod, new_db, new_chain))

        o, n = dump(old_db), dump(new_db)
        rows = sum(len(v) - 1 for v in n.values())
        checked.append(f"{dept}: {len(n)} tables / {rows} rows")
        diffs = compare(dept, o, n)
        if diffs:
            failures.extend(diffs)
        print(f"[{'FAIL' if diffs else ' ok '}] {dept}: "
              f"{len(n)} tables, {rows} rows (x2 runs, idempotency included)")

    print("\n".join("  " + c for c in checked))
    if failures:
        print("\nMISMATCHES:")
        print("\n".join(failures[:20]))
        return 1
    print(f"\n0 mismatches across {len(DEPARTMENTS)} departments.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
