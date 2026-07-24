"""
Phase 3 - crash recovery for orphaned deployments.

The deployment pipeline is fire-and-forget; a worker restart leaves the row hung
in a non-terminal state. The reaper transitions stuck (old, non-terminal)
deployments to FAILED, and leaves fresh or already-terminal ones untouched.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.workforce.deployment.studio import DeploymentStudio
from app.workforce.models.core import DeploymentStatus, WorkforceDeployment
from app.services.scheduler import init_scheduler

pytestmark = pytest.mark.asyncio


def _dep(db, *, status, started_minutes_ago):
    return WorkforceDeployment(
        id=str(uuid.uuid4()),
        tenant_id="tenant_reap",
        status=status,
        current_step="agents_deploying",
        started_at=datetime.now(timezone.utc) - timedelta(minutes=started_minutes_ago),
    )


def test_scheduler_registers_reaper_job():
    ids = {j.id for j in init_scheduler().get_jobs()}
    assert "deployment_reaper_job" in ids


async def test_reaper_fails_stuck_but_spares_fresh_and_terminal(db):
    stuck = _dep(db, status=DeploymentStatus.AGENTS_DEPLOYING, started_minutes_ago=120)
    fresh = _dep(db, status=DeploymentStatus.WORKFORCE_GENERATING, started_minutes_ago=2)
    done = _dep(db, status=DeploymentStatus.ACTIVE, started_minutes_ago=120)
    db.add_all([stuck, fresh, done])
    await db.commit()

    recovered = await DeploymentStudio.recover_orphaned_deployments(db, stuck_after_minutes=30)

    assert stuck.id in recovered
    assert fresh.id not in recovered
    assert done.id not in recovered

    await db.refresh(stuck)
    await db.refresh(fresh)
    await db.refresh(done)
    assert stuck.status == DeploymentStatus.FAILED
    assert stuck.error_log and stuck.error_log[-1]["recoverable"] is True
    assert fresh.status == DeploymentStatus.WORKFORCE_GENERATING
    assert done.status == DeploymentStatus.ACTIVE
