"""
KAEOS Workforce Layer — Department Runtime

Manages the active lifecycle of a deployed department. 
Handles pausing, resuming, and scaling agents based on load.
"""
import logging
from datetime import datetime, timezone, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func as sqlfunc

from app.workforce.models.core import Department, DepartmentAgent
from app.models.domain import SkillExecution
from app.services.event_bus import event_bus, EventType

logger = logging.getLogger(__name__)


class DepartmentRuntime:
    
    @staticmethod
    async def compute_health_score(db: AsyncSession, tenant_id: str, department_slug: str) -> float:
        """Compute real health score from SkillExecution success rates for this department."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=7)
        result = await db.execute(
            select(
                sqlfunc.count(SkillExecution.id).label("total"),
                sqlfunc.sum(
                    sqlfunc.cast(SkillExecution.status == "COMPLETED", sqlfunc.Integer)
                ).label("succeeded")
            ).where(
                SkillExecution.tenant_id == tenant_id,
                SkillExecution.department == department_slug,
                SkillExecution.started_at >= cutoff,
            )
        )
        row = result.one_or_none()
        if row and row.total and row.total > 0:
            return round((row.succeeded or 0) / row.total, 3)
        # No execution data yet — return seeded baseline from Department record
        dept_q = await db.execute(
            select(Department).where(
                Department.tenant_id == tenant_id,
                Department.slug == department_slug,
            )
        )
        dept = dept_q.scalar_one_or_none()
        return dept.health_score if dept and dept.health_score else 0.9

    @staticmethod
    async def get_department_status(db: AsyncSession, department_id: str) -> dict:
        """Returns the real-time operational status of the department."""
        q = await db.execute(select(Department).where(Department.id == department_id))
        dept = q.scalar_one_or_none()
        
        if not dept:
            raise ValueError(f"Department {department_id} not found")
            
        return {
            "id": dept.id,
            "name": dept.name,
            "status": dept.status,
            "agent_count": dept.agent_count,
            "uptime_hours": (datetime.now(timezone.utc) - (dept.last_active_at or dept.created_at)).total_seconds() / 3600
        }

    @staticmethod
    async def pause_department(db: AsyncSession, department_id: str, reason: str = "Manual pause"):
        """Pauses all agents and processes in a department."""
        logger.info(f"Pausing department {department_id}: {reason}")
        
        q = await db.execute(select(Department).where(Department.id == department_id))
        dept = q.scalar_one_or_none()
        
        if dept:
            dept.status = "PAUSED"
            db.add(dept)
            
            # Pause all agents
            aq = await db.execute(select(DepartmentAgent).where(DepartmentAgent.department_id == department_id))
            for agent in aq.scalars():
                agent.status = "PAUSED"
                db.add(agent)
                
            await db.commit()
            
            await event_bus.emit(EventType.DEPARTMENT_PAUSED, {
                "department_id": department_id,
                "reason": reason
            }, tenant_id=dept.tenant_id)
            
    @staticmethod
    async def resume_department(db: AsyncSession, department_id: str):
        """Resumes a paused department."""
        logger.info(f"Resuming department {department_id}")
        
        q = await db.execute(select(Department).where(Department.id == department_id))
        dept = q.scalar_one_or_none()
        
        if dept:
            dept.status = "ACTIVE"
            dept.last_active_at = datetime.now(timezone.utc)
            db.add(dept)
            
            aq = await db.execute(select(DepartmentAgent).where(DepartmentAgent.department_id == department_id))
            for agent in aq.scalars():
                agent.status = "IDLE"  # Will pick up work automatically
                db.add(agent)
                
            await db.commit()
