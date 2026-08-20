"""S4.8 - the five genuine foreign keys (migration 0055_genuine_fks).

Of 84 `_id` columns without a FK, five always name a sibling row; they now carry
one, named identically on the model and in the migration. The only caller that
could hand the database an unknown parent id was /actuation/execute (a client-
supplied execution_id), which now 404s instead of dying in the INSERT.

SQLite does not enforce foreign keys here (no PRAGMA foreign_keys=ON in the
test engine), so nothing below asserts IntegrityError - the constraint itself is
proved by the metadata, the Postgres drift gate, and the integrator's orphan
probe; these tests pin the mapping and the route contract.
"""
import asyncio
import uuid

import pytest
from fastapi import HTTPException

from app.core.database import AsyncSessionLocal, Base
from app.models.domain import SkillExecution
from tests.test_actuation_gate import (  # noqa: F401 - fixtures register by import
    _body, _ensure_schema, _mute_side_channels, _tenant,
)

# (child table, column, parent table)
GENUINE_FKS = [
    ("mission_steps", "mission_id", "missions"),
    ("action_records", "execution_id", "skill_executions"),
    ("department_agents", "blueprint_id", "agent_blueprints"),
    ("department_agents", "deployed_agent_id", "deployed_agents"),
    ("eng_engineers", "hr_employee_id", "hr_employees"),
]


@pytest.mark.parametrize("child,col,parent", GENUINE_FKS)
def test_column_has_exactly_one_fk_to_parent_pk(child, col, parent):
    fks = list(Base.metadata.tables[child].c[col].foreign_keys)
    assert len(fks) == 1, f"{child}.{col} should carry exactly one FK, has {len(fks)}"
    assert fks[0].target_fullname == f"{parent}.id"
    # Name mirrors migration 0055 so the drift gate compares one constraint.
    assert fks[0].constraint.name == f"fk_{child}_{col}"


@pytest.mark.parametrize("child,col,parent", GENUINE_FKS)
def test_sorted_tables_orders_parent_before_child(child, col, parent):
    """create_all and purge_tenant (reverse order) both rely on this ordering."""
    order = [t.name for t in Base.metadata.sorted_tables]
    assert order.index(parent) < order.index(child)


def _execute(body, tenant):
    from app.api.routes.actuation import execute_action

    async def run():
        async with AsyncSessionLocal() as db:
            return await execute_action(body, tenant=tenant, db=db)

    return asyncio.run(run())


async def _seed_execution(tenant_id: str) -> str:
    async with AsyncSessionLocal() as db:
        row = SkillExecution(tenant_id=tenant_id, status="SUCCESS_CLEAN")
        db.add(row)
        await db.commit()
        return row.id


def test_execute_unknown_execution_id_is_404():
    t = f"tenant_fk_{uuid.uuid4().hex[:6]}"
    with pytest.raises(HTTPException) as ei:
        _execute(_body(operation="CREATE", execution_id="exec-does-not-exist"), _tenant(t))
    assert ei.value.status_code == 404
    assert ei.value.detail == "Execution not found"


def test_execute_with_own_tenants_execution_proceeds():
    t = f"tenant_fk_{uuid.uuid4().hex[:6]}"
    ext_id = f"obj-{uuid.uuid4().hex[:6]}"
    exec_id = asyncio.run(_seed_execution(t))

    _execute(_body(operation="CREATE", external_id=ext_id), _tenant(t))
    out = _execute(_body(operation="UPDATE", external_id=ext_id, execution_id=exec_id), _tenant(t))
    assert out["status"] == "APPLIED"
    assert out["execution_id"] == exec_id


def test_execute_with_another_tenants_execution_is_404():
    """Never confirm a foreign id: same 404 as an unknown one, not 403."""
    mine = f"tenant_fk_{uuid.uuid4().hex[:6]}"
    theirs = f"tenant_fk_{uuid.uuid4().hex[:6]}"
    their_exec = asyncio.run(_seed_execution(theirs))

    with pytest.raises(HTTPException) as ei:
        _execute(_body(operation="CREATE", execution_id=their_exec), _tenant(mine))
    assert ei.value.status_code == 404
    assert ei.value.detail == "Execution not found"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
