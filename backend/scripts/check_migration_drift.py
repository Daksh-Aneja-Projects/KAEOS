#!/usr/bin/env python
"""CI guard: prove `alembic upgrade head` builds the full ORM schema.

Runs the migration chain and compares the resulting tables to ``Base.metadata``.
Fails (exit 1) if the migrations produce a database missing any model table —
i.e. if the migrations have drifted behind the models. This is the check whose
absence let the schema live only in `create_all`.

Database selection (the §14 fix): if ``DATABASE_URL_SYNC`` is ALREADY set in the
environment (e.g. the CI Postgres lane), the check runs against THAT database, so
the migration chain is validated on the real dialect (native enums / RLS /
pgvector / boolean DDL) — not only SQLite. Otherwise it defaults to a throwaway
SQLite file, so a local run needs no services. Tables are read via the SQLAlchemy
inspector, which is dialect-agnostic.

    python -m scripts.check_migration_drift                 # SQLite (default)
    DATABASE_URL_SYNC=postgresql+psycopg2://… python -m scripts.check_migration_drift
"""
import os
import sys
import tempfile

os.environ.setdefault("SECRET_KEY", "ci-drift-check-secret-key-000000")


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

    from alembic.config import Config
    from alembic import command
    from sqlalchemy import create_engine, inspect

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

    from app.core.database import Base
    engine = create_engine(sync_url)
    try:
        built = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()
    if tmp_path:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    model_tables = set(Base.metadata.tables)
    missing = sorted(model_tables - built)

    print(f"[drift] models define {len(model_tables)} tables; "
          f"migrations built {len(built & model_tables)} of them.")
    if missing:
        print(f"[drift] FAIL — {len(missing)} model table(s) are NOT created by "
              f"`alembic upgrade head`:")
        for t in missing:
            print(f"          - {t}")
        print("[drift] The migrations have drifted behind the models. Regenerate "
              "the baseline / add a migration so the schema is reproducible.")
        return 1

    print("[drift] OK — migrations build the complete model schema.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
