#!/usr/bin/env python
"""CI guard: native PG enum types must carry every label the models use.

The §14 hazard: a column typed ``Enum(SomeEnum)`` becomes a NATIVE Postgres enum
type. Adding a new member to ``SomeEnum`` in Python does NOT alter the existing PG
type — so on an already-upgraded prod DB every INSERT of the new member is
rejected until an ``ALTER TYPE … ADD VALUE`` migration lands. This script compares
each native enum type's labels in ``pg_enum`` against the Python enum members in
``Base.metadata`` and fails (exit 1) on any model-has-a-label-that-Postgres-lacks
drift.

No-op (exit 0) unless the target database is PostgreSQL — native enum labels are a
Postgres concern; on SQLite the values are plain strings.

    DATABASE_URL_SYNC=postgresql+psycopg2://… python -m scripts.check_enum_labels
"""
import os
import sys

os.environ.setdefault("SECRET_KEY", "ci-enum-check-secret-key-0000000")


def diff_enum_labels(model_map: dict, pg_map: dict) -> list:
    """Pure comparison. ``model_map``/``pg_map`` are {enum_type_name: set(labels)}.

    Returns a list of (type_name, missing_labels) where the model declares labels
    the PG type does not have — the INSERT-rejection drift. A type absent from PG
    entirely is reported with ALL its labels missing (its migration never ran).
    A PG type carrying EXTRA labels the model dropped is fine (old members linger
    harmlessly), so it is not reported.
    """
    drifts = []
    for name, model_labels in sorted(model_map.items()):
        pg_labels = pg_map.get(name)
        if pg_labels is None:
            drifts.append((name, sorted(model_labels)))
            continue
        missing = model_labels - pg_labels
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

    print(f"[enum] {len(model_map)} native enum types in the models; "
          f"{len(pg_map)} in Postgres.")
    if drifts:
        print("[enum] FAIL — model enum member(s) missing from the Postgres type "
              "(INSERT of these would be rejected on an upgraded DB):")
        for name, missing in drifts:
            print(f"          - {name}: add {missing} via `ALTER TYPE {name} ADD VALUE …`")
        return 1
    print("[enum] OK — every model enum label exists in its Postgres type.")
    return 0


if __name__ == "__main__":
    # Self-check of the pure diff before touching any DB.
    assert diff_enum_labels({"e": {"A", "B"}}, {"e": {"A", "B"}}) == []
    assert diff_enum_labels({"e": {"A", "B", "C"}}, {"e": {"A", "B"}}) == [("e", ["C"])]
    assert diff_enum_labels({"e": {"A"}}, {}) == [("e", ["A"])]
    assert diff_enum_labels({"e": {"A"}}, {"e": {"A", "B"}}) == []  # extra PG label is fine
    sys.exit(main())
