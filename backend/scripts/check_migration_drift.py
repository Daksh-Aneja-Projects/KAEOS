#!/usr/bin/env python
"""CI guard: prove `alembic upgrade head` builds the full ORM schema.

Runs the migration chain against a throwaway SQLite database and compares the
resulting tables to ``Base.metadata``. Fails (exit 1) if the migrations produce
a database that is missing any model table — i.e. if the migrations have drifted
behind the models. This is the check whose absence let the schema live only in
`create_all`; wire it into CI so migrations can never silently fall behind again.

    python -m scripts.check_migration_drift
"""
import os
import sys
import tempfile

os.environ.setdefault("SECRET_KEY", "ci-drift-check-secret-key-000000")


def main() -> int:
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    db_path = tmp.name.replace("\\", "/")
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{db_path}"
    os.environ["DATABASE_URL_SYNC"] = f"sqlite:///{db_path}"

    from alembic.config import Config
    from alembic import command
    import sqlite3

    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cfg = Config(os.path.join(here, "alembic.ini"))

    print("[drift] running `alembic upgrade head` on a fresh database…")
    command.upgrade(cfg, "head")

    # Idempotency: a second upgrade must be a no-op, not an error.
    command.upgrade(cfg, "head")

    from app.core.database import Base
    conn = sqlite3.connect(db_path)
    built = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    try:
        os.unlink(db_path)
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
