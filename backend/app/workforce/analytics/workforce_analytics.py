"""
KAEOS Workforce Layer — Analytics Engine

Aggregates metrics across the workforce layer to power the executive dashboard.
Calculates ROI, hours saved, and automation coverage.
"""
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.workforce.models.runtime import WorkforceMetrics

logger = logging.getLogger(__name__)

class WorkforceAnalytics:
    
    @staticmethod
    async def get_tenant_roi_summary(db: AsyncSession, tenant_id: str) -> dict:
        """Calculates total ROI and hours saved across all departments."""
        # Sum metrics
        q = await db.execute(
            select(
                func.sum(WorkforceMetrics.tasks_completed).label("total_tasks"),
                func.sum(WorkforceMetrics.hours_saved_estimate).label("total_hours_saved"),
                func.sum(WorkforceMetrics.cost_savings_estimate).label("total_cost_saved")
            )
            .where(WorkforceMetrics.tenant_id == tenant_id)
        )
        result = q.fetchone()
        
        return {
            "total_tasks_automated": result.total_tasks or 0,
            "total_hours_saved": result.total_hours_saved or 0.0,
            "total_cost_saved": result.total_cost_saved or 0.0
        }
