#!/usr/bin/env python
"""CI guard: prove `alembic upgrade head` builds the full ORM schema.

Runs the migration chain and diffs the resulting database against
``Base.metadata`` with alembic's own autogenerate comparator
(``alembic.autogenerate.compare_metadata``) — the same engine that decides what
a new revision would contain. An empty diff means a fresh ``alembic upgrade
head`` reproduces the models exactly. Anything else is drift, reported in BOTH
directions:

* ``in models, NOT in migrations`` — the drift that matters most: prod would come
  up missing a table/column/index the code expects;
* ``in migrations, NOT in models`` — a model was dropped or renamed without a
  migration to match (or, as with ``ops_work_orders`` below, a model module that
  never gets imported);
* ``differs`` — same object, different type / nullability / server default.

Column TYPE and SERVER DEFAULT are compared too — the same ``compare_type`` /
``compare_server_default`` options ``alembic/env.py`` now sets, so this gate sees
exactly what ``alembic revision --autogenerate`` would — but ONLY on Postgres;
see the note at ``full = …`` for why SQLite cannot participate in those two.

Why this had to be rewritten (§M9.2): the previous version compared
``set(Base.metadata.tables)`` to the table NAMES built by the migration chain —
but ``0001`` was literally ``Base.metadata.create_all()``, so the gate compared
the models to themselves and COULD NOT FAIL. ``0001`` is now literal DDL, which
is what makes this comparison meaningful at all.

Database selection (the §14 fix): if ``DATABASE_URL_SYNC`` is ALREADY set in the
environment (e.g. the CI Postgres lane), the check runs against THAT database, so
the migration chain is validated on the real dialect (native enums / RLS /
pgvector / boolean DDL) — not only SQLite. Otherwise it defaults to a throwaway
SQLite file, so a local run needs no services.

    python -m scripts.check_migration_drift                 # SQLite (default)
    DATABASE_URL_SYNC=postgresql+psycopg2://… python -m scripts.check_migration_drift
"""
import os
import sys
import tempfile

os.environ.setdefault("SECRET_KEY", "ci-drift-check-secret-key-000000")

# Pre-existing drift, accepted so the gate ratchets instead of failing on day
# one. Each entry is a real defect someone must fix; NEW drift of any kind still
# fails the build. Delete an entry the moment its cause is fixed — a stale entry
# is reported as such and also fails.
KNOWN_DRIFT = {
    # app/core/database.py's model-registration list imports the package
    # `app.operations.models`, whose __init__ does not pull in `.facilities`.
    # The table is real (migration 0049, model app/operations/models/facilities.py);
    # it only reaches Base.metadata once a router imports it.
    "remove_table:ops_work_orders",
    "remove_index:ops_work_orders.ix_ops_work_orders_tenant_id",
}

_DIRECTION = {"add": "in models, NOT in migrations",
              "remove": "in migrations, NOT in models",
              "modify": "differs"}


def describe(el) -> tuple:
    """One autogenerate diff element -> (stable key, human-readable line)."""
    op = el[0]
    if op in ("add_table", "remove_table"):
        t = el[1]
        return f"{op}:{t.name}", f"table {t.name} ({len(t.columns)} columns)"
    if op in ("add_index", "remove_index"):
        ix = el[1]
        cols = ", ".join(str(getattr(c, "name", c)) for c in ix.expressions)
        return (f"{op}:{ix.table.name}.{ix.name}",
                f"index {ix.name} on {ix.table.name} ({cols})"
                f"{' UNIQUE' if ix.unique else ''}")
    if op in ("add_column", "remove_column"):
        _, _schema, tname, col = el
        return (f"{op}:{tname}.{col.name}",
                f"column {tname}.{col.name} {col.type} nullable={col.nullable} "
                f"server_default={getattr(col.server_default, 'arg', None)}")
    if op in ("add_constraint", "remove_constraint", "add_fk", "remove_fk"):
        c = el[1]
        tname = getattr(getattr(c, "table", None), "name", "?")
        ident = c.name or ",".join(sorted(x.name for x in getattr(c, "columns", [])))
        return f"{op}:{tname}.{ident}", f"{type(c).__name__} {ident} on {tname}"
    if op.startswith("modify_"):
        _, _schema, tname, cname, _kw, old, new = el
        attr = op.split("_", 1)[1]
        return (f"{op}:{tname}.{cname}",
                f"{tname}.{cname} {attr}: models={new!r} migrations={old!r}")
    return f"{op}:{el!r}", repr(el)  # future alembic op we don't render specially


def flatten(diffs) -> list:
    """compare_metadata nests per-column alterations one list deep."""
    out = []
    for d in diffs:
        out.extend(d if isinstance(d, list) else [d])
    return out


def main() -> int:
    # Respect an externally-provided database (the Postgres CI lane); only fall
    # back to a throwaway SQLite file when none is configured.
    external = bool(os.environ.get("DATABASE_URL_SYNC") or os.environ.get("DATABASE_URL"))
    tmp_path = None
    if not external:
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        tmp_path = tmp.name.replace("\\", "/")
        os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{tmp_path}"
        os.environ["DATABASE_URL_SYNC"] = f"sqlite:///{tmp_path}"

    sync_url = os.environ["DATABASE_URL_SYNC"]
    dialect = sync_url.split(":", 1)[0].split("+", 1)[0]
    # Column type and server default are only compared on Postgres. SQLite's
    # reflection cannot round-trip either — it returns every `func.now()` as a
    # text CURRENT_TIMESTAMP clause (313 false "differs" on this schema) and has
    # no pgvector, so VECTOR(1536) reflects back as NUMERIC(1536). Tables,
    # columns, nullability, indexes and constraints are still compared on SQLite;
    # the CI lane that gates merges runs on Postgres and compares everything.
    full = dialect == "postgresql"

    from alembic.config import Config
    from alembic import command
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from sqlalchemy import create_engine

    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cfg = Config(os.path.join(here, "alembic.ini"))

    # Forward path (what ships to prod): exercise the full DDL from an EMPTY
    # database. On the external Postgres lane the caller provides a clean DB, so
    # every native-enum/RLS/pgvector/boolean statement actually runs here — the
    # validation whose absence let a Postgres-only DDL bug ship before.
    print(f"[drift] running `alembic upgrade head` on {dialect}…")
    command.upgrade(cfg, "head")
    # Idempotency: a second upgrade must be a no-op, not an error.
    command.upgrade(cfg, "head")

    # Imported AFTER the upgrade on purpose: alembic loads every version module,
    # and a few model modules reach Base.metadata only via those imports.
    from app.core.database import Base
    engine = create_engine(sync_url)
    try:
        with engine.connect() as conn:
            ctx = MigrationContext.configure(
                conn, opts={"compare_type": full, "compare_server_default": full},
            )
            diffs = flatten(compare_metadata(ctx, Base.metadata))
    finally:
        engine.dispose()
    if tmp_path:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    print(f"[drift] models define {len(Base.metadata.tables)} tables; "
          f"autogenerate reports {len(diffs)} difference(s) "
          f"({'incl.' if full else 'EXCL.'} column type + server default).")

    seen, real = set(), []
    for el in diffs:
        key, text = describe(el)
        seen.add(key)
        if key not in KNOWN_DRIFT:
            real.append((el[0].split("_", 1)[0], key, text))

    # Only the full (Postgres) comparison observes every allowlisted entry, so
    # only it can prove one has become stale.
    stale = sorted(KNOWN_DRIFT - seen) if full else []
    for key in stale:
        print(f"[drift] STALE allowlist entry (drift is gone): {key}")
    if seen & KNOWN_DRIFT:
        print(f"[drift] {len(seen & KNOWN_DRIFT)} known/accepted drift(s) ignored "
              f"— see KNOWN_DRIFT in this file.")

    if real:
        print(f"[drift] FAIL — {len(real)} unaccepted schema difference(s) between "
              f"the models and `alembic upgrade head`:")
        for kind, key, text in sorted(real):
            print(f"          [{_DIRECTION.get(kind, kind)}] {text}")
        print("[drift] Add a migration so `alembic upgrade head` reproduces the "
              "models (or fix the models if the migration is right).")
    if real or stale:
        return 1

    print("[drift] OK — `alembic upgrade head` reproduces the model schema.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
