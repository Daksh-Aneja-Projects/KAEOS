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


def register_all() -> None:
    """Register every durable-job handler. Idempotent."""
    job_queue.register_handler("deploy_pipeline", _run_deploy_pipeline)
    logger.info("[JobQueue] registered %d handler(s)", 1)
