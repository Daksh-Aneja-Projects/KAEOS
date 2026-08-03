"""
KAEOS Workforce Layer — Analytics Engine

Aggregates metrics across the workforce layer to power the executive dashboard.

Reports tasks automated (measured from real rows) and, where the tenant has
configured a human baseline, hours and cost saved. Hours-saved is never derived
by KAEOS: see ``HOURS_SAVED_NOTE`` in ``app/workforce/models/core.py``.
"""
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.config import get_settings
from app.workforce.models.core import hours_saved_payload
from app.workforce.models.runtime import WorkforceMetrics

logger = logging.getLogger(__name__)

class WorkforceAnalytics:

    @staticmethod
    async def get_tenant_roi_summary(db: AsyncSession, tenant_id: str) -> dict:
        """Total tasks automated, plus hours/cost saved when a baseline exists.

        `hours_saved_estimate` and `cost_savings_estimate` are tenant-supplied
        columns. When neither is populated the ROI figures come back null with a
        note rather than 0.0, which would read as a measured "saved nothing".
        """
        q = await db.execute(
            select(
                func.sum(WorkforceMetrics.tasks_completed).label("total_tasks"),
                func.sum(WorkforceMetrics.hours_saved_estimate).label("total_hours_saved"),
                func.sum(WorkforceMetrics.cost_savings_estimate).label("total_cost_saved")
            )
            .where(WorkforceMetrics.tenant_id == tenant_id)
        )
        result = q.fetchone()

        roi = hours_saved_payload(
            result.total_hours_saved if result else None,
            get_settings().LOADED_HOURLY_RATE_USD,
            result.total_cost_saved if result else None,
        )
        return {
            "total_tasks_automated": (result.total_tasks or 0) if result else 0,
            "total_hours_saved": roi["hours_saved"],
            "total_cost_saved": roi["cost_saved"],
            "hours_saved_basis": roi["hours_saved_basis"],
            "hours_saved_note": roi["hours_saved_note"],
        }
