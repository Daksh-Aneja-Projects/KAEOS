"""
KAEOS Workforce Layer — Deployment State Machine

Manages the multi-step deployment of a department from a domain pack.
Validates transitions and handles rollback on failure.
"""
import logging
import traceback
from datetime import datetime, timezone
from typing import Dict, Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.workforce.models.core import WorkforceDeployment, DeploymentStatus
from app.workforce.models.domain_pack import DomainPack

logger = logging.getLogger(__name__)


class DeploymentStateMachine:
    
    @staticmethod
    async def create_deployment(db: AsyncSession, tenant_id: str, pack_id: str, config: Dict[str, Any]) -> WorkforceDeployment:
        """Starts a new deployment."""
        q = await db.execute(select(DomainPack).where(DomainPack.id == pack_id))
        pack = q.scalar_one_or_none()
        if not pack:
            raise ValueError(f"Domain pack {pack_id} not found")
            
        deployment = WorkforceDeployment(
            tenant_id=tenant_id,
            domain_pack_id=pack_id,
            domain_pack_slug=pack.slug,
            status=DeploymentStatus.INIT,
            current_step="init",
            deployment_options=config,
            selected_capabilities=config.get("capabilities", []),
            connected_systems=config.get("systems", []),
            employee_count=config.get("employee_count", 0),
            progress_pct=5.0
        )
        
        DeploymentStateMachine._log_step(deployment, "INIT", "STARTED", "Deployment initialized")
        db.add(deployment)
        await db.commit()
        await db.refresh(deployment)
        
        return deployment

    @staticmethod
    async def transition(db: AsyncSession, deployment_id: str, next_status: DeploymentStatus, details: str = "") -> WorkforceDeployment:
        """Transitions deployment to the next state."""
        q = await db.execute(select(WorkforceDeployment).where(WorkforceDeployment.id == deployment_id))
        deployment = q.scalar_one_or_none()
        
        if not deployment:
            raise ValueError(f"Deployment {deployment_id} not found")
            
        if deployment.status in [DeploymentStatus.FAILED, DeploymentStatus.ROLLED_BACK]:
            raise ValueError(f"Cannot transition from terminal state {deployment.status}")
            
        # Log completion of current step
        DeploymentStateMachine._log_step(deployment, deployment.status.value, "COMPLETED", "Moving to next phase")
        
        # Update state
        deployment.status = next_status
        deployment.current_step = next_status.value.lower()
        
        # Update progress
        progress_map = {
            DeploymentStatus.PACK_SELECTED: 10.0,
            DeploymentStatus.SYSTEMS_CONNECTING: 20.0,
            DeploymentStatus.INTEGRATIONS_MAPPING: 30.0,
            DeploymentStatus.WORKFORCE_GENERATING: 50.0,
            DeploymentStatus.AGENTS_DEPLOYING: 70.0,
            DeploymentStatus.KNOWLEDGE_SEEDING: 85.0,
            DeploymentStatus.RUNTIME_STARTING: 95.0,
            DeploymentStatus.ACTIVE: 100.0
        }
        deployment.progress_pct = progress_map.get(next_status, deployment.progress_pct)
        
        if next_status == DeploymentStatus.ACTIVE:
            deployment.completed_at = datetime.now(timezone.utc)
            
        # Update associated Department status
        if deployment.department_id:
            from app.workforce.models.core import Department, DepartmentStatus
            dept_q = await db.execute(select(Department).where(Department.id == deployment.department_id))
            dept = dept_q.scalar_one_or_none()
            if dept:
                if next_status == DeploymentStatus.ACTIVE:
                    dept.status = DepartmentStatus.ACTIVE
                    dept.deployed_at = datetime.now(timezone.utc)
                    dept.health_score = 1.0
                elif next_status in [DeploymentStatus.FAILED, DeploymentStatus.ROLLED_BACK]:
                    dept.status = DepartmentStatus.DEGRADED
                else:
                    dept.status = DepartmentStatus.DEPLOYING
                db.add(dept)
            
        # Log start of next step
        DeploymentStateMachine._log_step(deployment, next_status.value, "STARTED", details)
        
        db.add(deployment)
        await db.commit()
        await db.refresh(deployment)

        # ── Single-owner deployment work ─────────────────────────────────────
        # NOTE: this FSM is intentionally a *pure* state/progress tracker. It does
        # NOT trigger workforce generation, agent deployment, or knowledge seeding.
        # The DeploymentStudio pipeline (studio.py) is the single owner of that
        # work and calls the generator explicitly at each phase. A previous version
        # auto-triggered the generator here AND in the studio, causing every
        # department/agent to be created twice. Do not re-add generator calls here.

        logger.info(f"Deployment {deployment_id} transitioned to {next_status}")
        return deployment

    @staticmethod
    async def fail_deployment(db: AsyncSession, deployment_id: str, error: Exception) -> WorkforceDeployment:
        """Fails a deployment and logs the error."""
        q = await db.execute(select(WorkforceDeployment).where(WorkforceDeployment.id == deployment_id))
        deployment = q.scalar_one_or_none()
        
        if not deployment:
            return None
            
        error_msg = str(error)
        tb = traceback.format_exc()
        
        error_entry = {
            "step": deployment.current_step,
            "error": error_msg,
            "traceback": tb,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        current_errors = list(deployment.error_log or [])
        current_errors.append(error_entry)
        deployment.error_log = current_errors
        
        deployment.status = DeploymentStatus.FAILED
        deployment.completed_at = datetime.now(timezone.utc)
        
        # Update associated Department status to DEGRADED on failure
        if deployment.department_id:
            from app.workforce.models.core import Department, DepartmentStatus
            dept_q = await db.execute(select(Department).where(Department.id == deployment.department_id))
            dept = dept_q.scalar_one_or_none()
            if dept:
                dept.status = DepartmentStatus.DEGRADED
                db.add(dept)
        
        DeploymentStateMachine._log_step(deployment, deployment.current_step.upper(), "FAILED", error_msg)
        
        db.add(deployment)
        await db.commit()
        await db.refresh(deployment)
        
        logger.error(f"Deployment {deployment_id} failed: {error_msg}")
        return deployment

    @staticmethod
    def _log_step(deployment: WorkforceDeployment, step: str, status: str, details: str):
        """Appends a step log entry to the deployment."""
        steps = list(deployment.deployment_steps or [])
        steps.append({
            "step": step,
            "status": status,
            "details": details,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
        deployment.deployment_steps = steps
