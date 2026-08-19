#!/usr/bin/env python
"""CI guard: native PG enum types must carry every label the models use.

This codebase uses NATIVE Postgres enums, deliberately: every ``Enum(SomeEnum)``
column compiles to ``CREATE TYPE … AS ENUM``. As of 0052 that is 86 distinct
native types and ZERO ``native_enum=False`` columns — verify with
``python -m scripts.check_enum_labels`` itself, which prints both counts.

The §14 hazard: adding a new member to ``SomeEnum`` in Python does NOT alter the
existing PG type — so on an already-upgraded prod DB every INSERT of the new
member is rejected until an ``ALTER TYPE … ADD VALUE`` migration lands. This
script compares each native enum type's labels in ``pg_enum`` (on a database
built by ``alembic upgrade head``) against the Python enum members in
``Base.metadata`` and fails (exit 1) on drift.

No-op (exit 0) unless the target database is PostgreSQL — native enum labels are a
Postgres concern; on SQLite the values are plain strings.

    DATABASE_URL_SYNC=postgresql+psycopg2://… python -m scripts.check_enum_labels
"""
import os
import sys

os.environ.setdefault("SECRET_KEY", "ci-enum-check-secret-key-0000000")


def diff_enum_labels(model_map: dict, pg_map: dict) -> list:
    """Pure comparison. ``model_map``/``pg_map`` are {enum_type_name: set(labels)}.

    Returns a list of (type_name, missing_labels) — every label the models use that
    the migration-built database cannot store. Two ways that happens:

    * the type EXISTS but LACKS labels — a member was added to the Python enum with
      no ``ALTER TYPE … ADD VALUE`` migration (missing = just those labels);
    * the type is ABSENT ENTIRELY — the migration chain never ran ``CREATE TYPE``
      for it, so *every* label is unstorable (missing = all of them). Callers tell
      the two apart with ``name in pg_map``.

    A PG type carrying EXTRA labels the model dropped is fine — old members linger
    harmlessly — so extras are ignored.
    """
    drifts = []
    for name, model_labels in sorted(model_map.items()):
        missing = model_labels - pg_map.get(name, set())
        if missing:
            drifts.append((name, sorted(missing)))
    return drifts


def _model_enum_map() -> dict:
    """{pg_enum_type_name: set(str member values)} for every NATIVE Enum column."""
    from sqlalchemy import Enum as SAEnum
    from app.core.database import Base

    out: dict = {}
    for table in Base.metadata.tables.values():
        for col in table.columns:
            t = col.type
            if isinstance(t, SAEnum) and getattr(t, "native_enum", True) and t.name:
                out.setdefault(t.name, set()).update(t.enums or [])
    return out


def _pg_enum_map(sync_url: str) -> dict:
    """{typname: set(enumlabel)} from the live Postgres catalog."""
    from sqlalchemy import create_engine, text

    engine = create_engine(sync_url)
    try:
        with engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT t.typname, e.enumlabel FROM pg_enum e "
                "JOIN pg_type t ON t.oid = e.enumtypid"
            )).fetchall()
    finally:
        engine.dispose()
    out: dict = {}
    for typname, label in rows:
        out.setdefault(typname, set()).add(label)
    return out


def main() -> int:
    sync_url = os.environ.get("DATABASE_URL_SYNC") or os.environ.get("DATABASE_URL") or ""
    if "postgres" not in sync_url:
        print(f"[enum] skip — target is not Postgres ({sync_url.split(':', 1)[0] or 'unset'}).")
        return 0

    model_map = _model_enum_map()
    pg_map = _pg_enum_map(sync_url)
    drifts = diff_enum_labels(model_map, pg_map)

    absent = sum(1 for n in model_map if n not in pg_map)
    print(f"[enum] {len(model_map)} model enum types; {len(pg_map)} native in the "
          f"migration-built Postgres DB; {absent} model type(s) absent entirely.")
    if drifts:
        print("[enum] FAIL — model enum label(s) the migration-built DB cannot store "
              "(INSERT of these would be rejected on an upgraded DB):")
        for name, missing in drifts:
            if name in pg_map:
                print(f"          - {name}: add {missing} via `ALTER TYPE {name} ADD VALUE …`")
            else:
                print(f"          - {name}: TYPE MISSING — no migration ever ran "
                      f"`CREATE TYPE {name} AS ENUM {tuple(missing)}`")
        return 1
    print("[enum] OK — every model enum label exists in its Postgres type.")
    return 0


if __name__ == "__main__":
    # Self-check of the pure diff before touching any DB.
    assert diff_enum_labels({"e": {"A", "B"}}, {"e": {"A", "B"}}) == []
    assert diff_enum_labels({"e": {"A", "B", "C"}}, {"e": {"A", "B"}}) == [("e", ["C"])]
    assert diff_enum_labels({"e": {"A", "B"}}, {}) == [("e", ["A", "B"])]  # type never created
    assert diff_enum_labels({"e": {"A"}}, {"e": {"A", "B"}}) == []  # extra PG label is fine
    sys.exit(main())
