"""Five genuine foreign keys on `_id` columns that always name a sibling row.

84 `_id` columns carry no FK; these five are the ones whose value is always (and
must be) the PK of a sibling table, so the database now guarantees it:

  mission_steps.mission_id            -> missions.id          (NOT NULL)
  action_records.execution_id         -> skill_executions.id  (nullable)
  department_agents.blueprint_id      -> agent_blueprints.id  (nullable)
  department_agents.deployed_agent_id -> deployed_agents.id   (nullable)
  eng_engineers.hr_employee_id        -> hr_employees.id      (nullable)

Orphan sweep rule: a FK cannot be created while rows violate it, so each ADD
CONSTRAINT is preceded by a sweep. A NULLABLE column loses only the dangling
pointer (SET NULL - the row itself is still meaningful without it). The NOT NULL
column, mission_steps.mission_id, cannot be nulled, so a step whose mission row no
longer exists is DELETED: every mission reader joins missions (the step is
unreachable) and the one tenant-only reader, the Foresight decision queue, would
otherwise surface it as a ghost checkpoint pointing at a mission that does not
exist. Both counts are logged.

Constraint names are explicit and mirrored on the models (ForeignKey(..., name=))
so the drift gate compares one constraint, never two differently-named copies.

Dialect: on Postgres this is a plain ALTER TABLE ADD CONSTRAINT. SQLite cannot
ADD CONSTRAINT, and the drift gate's SQLite lane builds the schema from this
literal-DDL chain (not create_all), so it must get the FKs too: batch mode
recreates the table there and passes straight through on Postgres. Inspector-
guarded: a missing table or an already-present FK (by constrained column +
referred table) is skipped, so DEV_MODE databases pre-built by create_all no-op.

Revision ID: 0055_genuine_fks
Revises: 0054_legal_exposure_numeric
"""
import logging

import sqlalchemy as sa
from alembic import op

revision = "0055_genuine_fks"
down_revision = "0054_legal_exposure_numeric"
branch_labels = None
depends_on = None

_log = logging.getLogger("alembic.runtime.migration")

# (constraint name, child table, child column, parent table, child column NOT NULL?)
_FKS = [
    ("fk_mission_steps_mission_id", "mission_steps", "mission_id", "missions", True),
    ("fk_action_records_execution_id", "action_records", "execution_id", "skill_executions", False),
    ("fk_department_agents_blueprint_id", "department_agents", "blueprint_id", "agent_blueprints", False),
    ("fk_department_agents_deployed_agent_id", "department_agents", "deployed_agent_id",
     "deployed_agents", False),
    ("fk_eng_engineers_hr_employee_id", "eng_engineers", "hr_employee_id", "hr_employees", False),
]

# SQLite reflection drops constraint names; every name above is exactly
# fk_<table>_<column>, so this convention re-derives them for the batch drop.
_NAMING = {"fk": "fk_%(table_name)s_%(column_0_name)s"}


def _has_fk(insp, table: str, col: str, parent: str) -> bool:
    return any(
        fk["constrained_columns"] == [col] and fk["referred_table"] == parent
        for fk in insp.get_foreign_keys(table)
    )


def _sweep_orphans(bind, table: str, col: str, parent: str, not_null: bool) -> None:
    orphan = (f"{col} IS NOT NULL AND NOT EXISTS "
              f"(SELECT 1 FROM {parent} p WHERE p.id = {table}.{col})")
    if not_null:
        res = bind.execute(sa.text(f"DELETE FROM {table} WHERE {orphan}"))
        verb = "deleted"
    else:
        res = bind.execute(sa.text(f"UPDATE {table} SET {col} = NULL WHERE {orphan}"))
        verb = "nulled"
    n = res.rowcount or 0
    if n:
        _log.warning("[0055] %s %d orphan row(s) in %s.%s (no matching %s.id)",
                     verb, n, table, col, parent)
    else:
        _log.info("[0055] no orphans in %s.%s", table, col)


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())
    for name, table, col, parent, not_null in _FKS:
        if table not in tables or parent not in tables:
            continue
        if _has_fk(insp, table, col, parent):
            continue
        _sweep_orphans(bind, table, col, parent, not_null)
        with op.batch_alter_table(table) as batch_op:
            batch_op.create_foreign_key(name, parent, [col], ["id"])


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())
    for name, table, col, parent, _nn in reversed(_FKS):
        if table not in tables or not _has_fk(insp, table, col, parent):
            continue
        with op.batch_alter_table(table, naming_convention=_NAMING) as batch_op:
            batch_op.drop_constraint(name, type_="foreignkey")
