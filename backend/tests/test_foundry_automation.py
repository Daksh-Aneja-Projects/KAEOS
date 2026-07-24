"""
Phase 4D - the AI Foundry improvement loop is automated (not manual).

Asserts the scheduler registers the foundry mining job, and that mining is
idempotent (safe to run on a cadence): the second pass creates nothing new.
"""
import uuid

import pytest

from app.models.domain import SkillExecution
from app.services.foundry import dataset_builder
from app.services.scheduler import init_scheduler

pytestmark = pytest.mark.asyncio


def test_scheduler_registers_foundry_mining_job():
    scheduler = init_scheduler()
    job_ids = {j.id for j in scheduler.get_jobs()}
    assert "foundry_mining_job" in job_ids
    assert "decay_checks_job" in job_ids
    assert "retention_sweep_job" in job_ids


async def test_mining_is_idempotent(db):
    tenant = "tenant_foundry"
    # A clean, autonomous success is mineable as a GOLD training example.
    db.add(SkillExecution(
        id=str(uuid.uuid4()),
        skill_id_name="refund_small",
        tenant_id=tenant,
        status="SUCCESS_CLEAN",
        hitl_required=False,
        outcome_type="SUCCESS_CLEAN",
        task_intent="approve a small refund",
    ))
    await db.commit()

    first = await dataset_builder.mine_executions(db, tenant)
    assert first["created"] >= 1

    second = await dataset_builder.mine_executions(db, tenant)
    assert second["created"] == 0, "already-mined executions must not be re-mined"
