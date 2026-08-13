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
    logger.info("[JobQueue] registered %d handler(s)", 2)
