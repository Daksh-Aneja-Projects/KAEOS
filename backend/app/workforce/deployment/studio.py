"""
KAEOS Workforce Layer — Deployment Studio

Orchestrates the actual work of deploying a department.
Coordinates the state machine, workforce generator, and integrations.
"""
import logging
import asyncio
from typing import Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession

from app.workforce.deployment.state_machine import DeploymentStateMachine
from app.workforce.models.core import DeploymentStatus

logger = logging.getLogger(__name__)


class DeploymentStudio:
    
    @staticmethod
    async def start_deployment_workflow(db: AsyncSession, tenant_id: str, pack_id: str, config: Dict[str, Any]) -> str:
        """
        Kicks off the deployment workflow.
        Returns the deployment_id immediately while the heavy lifting happens in the background.
        """
        # 1. Initialize deployment
        deployment = await DeploymentStateMachine.create_deployment(db, tenant_id, pack_id, config)
        
        # 2. Start background task for the actual deployment
        asyncio.create_task(DeploymentStudio._run_deployment_pipeline(tenant_id, deployment.id, config))
        
        return deployment.id
        
    # Terminal states — a deployment here is done and never needs recovery.
    _TERMINAL = {DeploymentStatus.ACTIVE, DeploymentStatus.FAILED, DeploymentStatus.ROLLED_BACK}

    @staticmethod
    async def recover_orphaned_deployments(db: AsyncSession, stuck_after_minutes: int = 30) -> list:
        """Fail deployments left stuck mid-pipeline by a crashed/restarted worker.

        The pipeline runs as a fire-and-forget task in whatever worker received
        the POST, so a worker restart mid-deploy leaves the row hung in a
        non-terminal state forever. This transitions any non-terminal deployment
        whose ``started_at`` is older than the threshold to FAILED (with a
        recoverable error-log entry) so it is visible and actionable instead of
        silently stuck. Returns the recovered deployment ids.
        """
        from datetime import datetime, timedelta, timezone
        from sqlalchemy import select
        from app.workforce.models.core import WorkforceDeployment

        cutoff = datetime.now(timezone.utc) - timedelta(minutes=stuck_after_minutes)
        rows = (await db.execute(
            select(WorkforceDeployment).where(
                WorkforceDeployment.status.notin_(list(DeploymentStudio._TERMINAL)),
                WorkforceDeployment.started_at < cutoff,
            )
        )).scalars().all()

        recovered = []
        for d in rows:
            log = list(d.error_log or [])
            log.append({
                "step": d.current_step,
                "error": "orphaned: no active runner (worker restart?) - auto-failed by reaper",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "recoverable": True,
            })
            d.error_log = log
            d.status = DeploymentStatus.FAILED
            d.completed_at = datetime.now(timezone.utc)
            recovered.append(d.id)
        if recovered:
            await db.commit()
            logger.warning("[DeploymentStudio] Reaped %d orphaned deployment(s): %s",
                           len(recovered), recovered)
        return recovered

    @staticmethod
    async def _run_deployment_pipeline(tenant_id: str, deployment_id: str, config: Dict[str, Any]):
        """The actual background deployment pipeline.

        This studio is the SINGLE OWNER of the real deployment work (structure
        generation, agent deployment, knowledge seeding). The state machine only
        tracks progress — it does not trigger any of this work (see state_machine.py).

        Each phase performs real, awaited work (connector health probe, integration
        mapping, generation). Any failure transitions the deployment to FAILED and
        the associated department to DEGRADED (handled by fail_deployment).
        """
        from app.core.database import AsyncSessionLocal
        from sqlalchemy import select
        from app.workforce.orchestration.workforce_generator import WorkforceGenerator
        from app.workforce.deployment.integration_mapper import (
            ConnectorHealthChecker, IntegrationMapper,
        )
        from app.workforce.models.core import WorkforceDeployment
        from app.workforce.models.domain_pack import DomainPack

        async with AsyncSessionLocal() as db:
            try:
                # Resolve the deployment + pack once for real work below.
                dep_res = await db.execute(
                    select(WorkforceDeployment).where(WorkforceDeployment.id == deployment_id)
                )
                deployment = dep_res.scalar_one()
                pack_res = await db.execute(
                    select(DomainPack).where(DomainPack.id == deployment.domain_pack_id)
                )
                pack = pack_res.scalar_one()
                connected_systems = deployment.connected_systems or config.get("systems", [])

                generator = WorkforceGenerator()

                # -- PACK_SELECTED (validate the pack really exists / has content)
                await DeploymentStateMachine.transition(
                    db, deployment_id, DeploymentStatus.PACK_SELECTED,
                    f"Validated pack '{pack.slug}' with {len(pack.capabilities or [])} capabilities",
                )

                # -- SYSTEMS_CONNECTING (real connector health probe)
                health = await ConnectorHealthChecker.check(db, tenant_id, connected_systems)
                await DeploymentStateMachine.transition(
                    db, deployment_id, DeploymentStatus.SYSTEMS_CONNECTING,
                    f"Connector health: {health['healthy']}/{health['total']} healthy",
                )

                # -- WORKFORCE_GENERATING (idempotent structure generation)
                await DeploymentStateMachine.transition(
                    db, deployment_id, DeploymentStatus.WORKFORCE_GENERATING,
                    "Generating department abstractions",
                )
                dept = await generator.generate_department_structure(db, tenant_id, deployment_id)

                # -- INTEGRATIONS_MAPPING (needs the department id; runs after structure)
                mapping = await IntegrationMapper.map(
                    db, tenant_id, dept.id,
                    pack.required_integrations or [], connected_systems,
                )
                await DeploymentStateMachine.transition(
                    db, deployment_id, DeploymentStatus.INTEGRATIONS_MAPPING,
                    f"Mapped integrations: {mapping['satisfied']}/{mapping['required']} satisfied",
                )

                # -- AGENTS_DEPLOYING (single owner)
                await DeploymentStateMachine.transition(
                    db, deployment_id, DeploymentStatus.AGENTS_DEPLOYING,
                    "Compiling and deploying agents",
                )
                await generator.deploy_agents(db, tenant_id, deployment_id, dept.id)

                # -- KNOWLEDGE_SEEDING (single owner)
                await DeploymentStateMachine.transition(
                    db, deployment_id, DeploymentStatus.KNOWLEDGE_SEEDING,
                    "Seeding enterprise knowledge base",
                )
                await generator.seed_knowledge(db, tenant_id, deployment_id, dept.id)

                # -- RUNTIME_STARTING (real: verify the department has runnable agents)
                from app.workforce.models.core import DepartmentAgent
                agents_res = await db.execute(
                    select(DepartmentAgent).where(DepartmentAgent.department_id == dept.id)
                )
                agent_count = len(agents_res.scalars().all())
                if agent_count == 0:
                    raise RuntimeError("Runtime start aborted: no agents were deployed")
                await DeploymentStateMachine.transition(
                    db, deployment_id, DeploymentStatus.RUNTIME_STARTING,
                    f"Starting runtime with {agent_count} agents",
                )

                # -- ACTIVE
                await DeploymentStateMachine.transition(
                    db, deployment_id, DeploymentStatus.ACTIVE,
                    "Department successfully deployed",
                )

            except Exception as e:
                logger.error(f"Deployment pipeline failed for {deployment_id}: {e}")
                # The session may hold a failed flush — clear it or the FAILED
                # transition itself dies with PendingRollbackError and the
                # deployment hangs at its last progress state forever.
                try:
                    await db.rollback()
                except Exception:
                    pass
                await DeploymentStateMachine.fail_deployment(db, deployment_id, e)
