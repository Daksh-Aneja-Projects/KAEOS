"""Zero-prompt (ghost) executions are governed, not phantom.

Regression suite for the C1 defect: predictive-ops wrote SkillExecution rows
stamped QUEUED (a status no gate produces) that nothing ever drained — billed
by usage rating and diluting the safe-autonomy denominator. Predictions now
enqueue a durable job whose handler runs the full gate pipeline.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from app.models.domain import Skill, SkillExecution
from app.models.jobs import Job
from app.services.predictive_ops import LatentIntent, PredictiveOpsEngine

T = "tenant_zero_prompt"


async def test_trigger_enqueues_job_and_writes_no_execution(db):
    db.add(Skill(id=str(uuid.uuid4()), skill_id="ops_predicted", tenant_id=T,
                 department="operations", status="ACTIVE", confidence=0.95))
    await db.commit()

    intent = LatentIntent(
        intent_type="AUTOMATED_PREDICTION", confidence=0.9,
        recommended_skill_id="ops_predicted",
        context={"tenant_id": T, "source_signal": "sig-1"},
    )
    job_id = await PredictiveOpsEngine.trigger_zero_prompt_execution(db, intent)

    job = (await db.execute(select(Job).where(Job.id == job_id))).scalar_one()
    assert job.job_type == "zero_prompt_execution"
    assert job.tenant_id == T
    assert job.payload["skill_id"] == "ops_predicted"

    # The old defect: a SkillExecution stamped QUEUED. There must be none.
    rows = (await db.execute(
        select(SkillExecution).where(SkillExecution.tenant_id == T)
    )).scalars().all()
    assert rows == []


def test_zero_prompt_handler_registered():
    from app.services import job_handlers, job_queue
    job_handlers.register_all()
    assert "zero_prompt_execution" in job_queue._HANDLERS


async def test_safe_autonomy_denominator_excludes_unevaluated_rows(db):
    """Legacy QUEUED ghost rows must not dilute the north star."""
    from app.services.safe_autonomy import compute_safe_autonomy
    now = datetime.now(timezone.utc)
    db.add(SkillExecution(id="za-1", tenant_id=T, skill_id_name="s",
                          status="SUCCESS_CLEAN", hitl_required=False,
                          started_at=now))
    db.add(SkillExecution(id="za-2", tenant_id=T, skill_id_name="s",
                          status="QUEUED", route_type="ZERO_PROMPT_AUTO",
                          started_at=now))
    await db.commit()
    result = await compute_safe_autonomy(db, T, days=7)
    assert result["total_executions"] == 1
    assert result["safe_autonomy_rate"] == 1.0
