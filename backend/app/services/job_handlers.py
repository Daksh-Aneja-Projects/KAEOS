"""KAEOS — durable job handlers registry.

Maps each ``job_type`` to the coroutine that performs its work. Imported once at
scheduler startup (and by tests) so handlers are registered before the queue
processor runs. Kept separate from ``job_queue`` to avoid import cycles with the
feature modules the handlers call into.
"""
import logging

from app.services import job_queue

logger = logging.getLogger(__name__)


async def _run_deploy_pipeline(payload: dict) -> None:
    """Handler for the workforce deployment pipeline (was fire-and-forget)."""
    from app.workforce.deployment.studio import DeploymentStudio
    await DeploymentStudio._run_deployment_pipeline(
        payload["tenant_id"], payload["deployment_id"], payload.get("config") or {},
    )


async def _run_zero_prompt_execution(payload: dict) -> None:
    """Run a predicted (zero-prompt "ghost") execution through the FULL gate
    pipeline — the same AgentExecutor path /skills/{id}/execute and missions
    use. Predictive-ops used to write a bare SkillExecution stamped QUEUED that
    nothing drained; the row that exists after this handler is a genuinely
    governed one (compliance, fairness, confidence/HITL, debate, actuation
    re-gate, audit, provenance).

    max_attempts is 1 (enqueue default): a mid-run crash surfaces as a FAILED
    job for the operator rather than silently re-running a governed action.
    """
    import uuid as _uuid

    from sqlalchemy import select

    from app.agents.runtime import AgentExecutor
    from app.core.database import AsyncSessionLocal
    from app.models.domain import Skill
    from app.services.compliance import ComplianceEngine
    from app.services.hitl_manager import hitl_manager

    async with AsyncSessionLocal() as db:
        skill = (await db.execute(
            select(Skill).where(
                Skill.id == payload["skill_db_id"],
                Skill.tenant_id == payload["tenant_id"],
            )
        )).scalar_one_or_none()
    if skill is None:
        # Prediction outlived the skill; nothing to govern, nothing to retry.
        logger.info("[ZeroPrompt] skill %s gone; dropping prediction",
                    payload.get("skill_id"))
        return

    skill_dict = {
        "skill_id": skill.skill_id,
        "skill_db_id": skill.id,
        "department": skill.department,
        "domain": skill.domain,
        "steps": skill.steps or [],
        "compliance_tags": skill.compliance_tags or [],
        "confidence": skill.confidence or 0.0,
        "guardrails": skill.guardrails or {},
        "always_hitl": bool(getattr(skill, "always_hitl", False)),
    }
    context = dict(payload.get("context") or {})
    context.update({
        "intent": "Auto-predicted from latent intent analysis",
        "tenant_id": skill.tenant_id,
        "execution_id": str(_uuid.uuid4()),
        "zero_prompt": True,
        "intent_confidence": payload.get("intent_confidence"),
    })

    executor = AgentExecutor(ComplianceEngine(), hitl_manager)
    result = await executor.execute_skill(skill_dict, context)
    logger.info("[ZeroPrompt] %s finished with status=%s",
                skill.skill_id, result.get("status"))


async def _run_hitl_resume(payload: dict) -> None:
    """Durable backstop for an approved HITL resume.

    Enqueued atomically with every approval; fires only after the backstop
    delay. The resume is idempotent on execution_id - if the immediate
    in-process attempt already finished (the normal case) this is a no-op.
    Raising on a False return lets the queue retry with backoff, so a crash
    between approval and completion can no longer lose an approved run.
    """
    from app.services.hitl_manager import hitl_manager
    ok = await hitl_manager._resume_from_hitl(
        payload["execution_id"], fallback_record=payload.get("fallback_record"),
    )
    if not ok:
        raise RuntimeError(
            f"HITL resume for {payload['execution_id']} did not complete"
        )


def register_all() -> None:
    """Register every durable-job handler. Idempotent."""
    job_queue.register_handler("deploy_pipeline", _run_deploy_pipeline)
    job_queue.register_handler("hitl_resume", _run_hitl_resume)
    job_queue.register_handler("zero_prompt_execution", _run_zero_prompt_execution)
    logger.info("[JobQueue] registered %d handler(s)", 3)
