from app.core.tenant import get_tenant_id
"""
KAEOS Workforce API — Analytics
Workforce-level metrics: hours saved, tasks automated, ROI, per-department breakdown.

Queries the WorkforceMetrics time-series table + denormalized Department counters.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func as sqlfunc

from app.core.database import get_db
from app.workforce.models.core import Department, DepartmentStatus, DepartmentAgent
from app.workforce.models.runtime import WorkforceMetrics

router = APIRouter(prefix="/workforce/analytics", tags=["Workforce — Analytics"])


@router.get("")
async def workforce_analytics(
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Aggregate workforce analytics — powers the ROI dashboard."""
    # Department-level aggregations
    dept_q = await db.execute(
        select(
            sqlfunc.count(Department.id),
            sqlfunc.sum(Department.tasks_completed_total),
            sqlfunc.sum(Department.hours_saved_total),
            sqlfunc.avg(Department.automation_coverage),
            sqlfunc.avg(Department.health_score),
        )
        .where(Department.tenant_id == tenant_id)
        .where(Department.status == DepartmentStatus.ACTIVE)
    )
    dept_row = dept_q.one_or_none()

    active_depts = dept_row[0] if dept_row else 0
    total_tasks = int(dept_row[1] or 0) if dept_row else 0
    total_hours_saved = float(dept_row[2] or 0) if dept_row else 0
    avg_automation = float(dept_row[3] or 0) if dept_row else 0
    avg_health = float(dept_row[4] or 0) if dept_row else 0

    # Agent fleet utilization
    agent_q = await db.execute(
        select(
            sqlfunc.count(DepartmentAgent.id),
            sqlfunc.sum(DepartmentAgent.tasks_handled),
            sqlfunc.avg(DepartmentAgent.health_score),
        )
        .where(DepartmentAgent.tenant_id == tenant_id)
        .where(DepartmentAgent.status == "ACTIVE")
    )
    agent_row = agent_q.one_or_none()
    active_agents = agent_row[0] if agent_row else 0
    int(agent_row[1] or 0) if agent_row else 0
    avg_agent_health = float(agent_row[2] or 0) if agent_row else 0

    # WorkforceMetrics time-series (latest daily aggregate)
    metrics_q = await db.execute(
        select(
            sqlfunc.sum(WorkforceMetrics.tasks_completed),
            sqlfunc.sum(WorkforceMetrics.hours_saved_estimate),
            sqlfunc.sum(WorkforceMetrics.cost_savings_estimate),
            sqlfunc.avg(WorkforceMetrics.automation_coverage_pct),
            sqlfunc.avg(WorkforceMetrics.agent_utilization_pct),
            sqlfunc.avg(WorkforceMetrics.human_escalation_rate),
        )
        .where(WorkforceMetrics.tenant_id == tenant_id)
    )
    m_row = metrics_q.one_or_none()

    metrics_tasks = int(m_row[0] or 0) if m_row else 0
    metrics_hours_saved = float(m_row[1] or 0) if m_row else 0
    metrics_cost_saved = float(m_row[2] or 0) if m_row else 0

    # Cost saved derives from the same live hours-saved figure via the loaded
    # hourly rate — prefer a real WorkforceMetrics cost if the time-series has
    # been populated, otherwise compute it so the ROI card is never a stale $0
    # while hours-saved is non-zero.
    from app.core.config import get_settings
    loaded_rate = get_settings().LOADED_HOURLY_RATE_USD
    effective_hours = max(total_hours_saved, metrics_hours_saved)
    derived_cost = effective_hours * loaded_rate
    effective_cost = max(metrics_cost_saved, derived_cost)
    metrics_automation = float(m_row[3] or 0) if m_row else 0
    metrics_utilization = float(m_row[4] or 0) if m_row else 0
    metrics_escalation = float(m_row[5] or 0) if m_row else 0

    # Per-department breakdown
    dept_breakdown_q = await db.execute(
        select(Department)
        .where(Department.tenant_id == tenant_id)
        .where(Department.status == DepartmentStatus.ACTIVE)
        .order_by(Department.hours_saved_total.desc())
    )
    departments = dept_breakdown_q.scalars().all()

    return {
        # Headline KPIs
        "departments_active": active_depts,
        "agents_active": active_agents,
        "total_tasks_completed": max(total_tasks, metrics_tasks),
        "total_hours_saved": round(effective_hours, 1),
        "total_cost_saved": round(effective_cost, 2),
        "loaded_hourly_rate_usd": loaded_rate,
        "automation_coverage_pct": round(max(avg_automation, metrics_automation) * 100, 1),
        "agent_utilization_pct": round(metrics_utilization * 100, 1),
        "human_escalation_rate_pct": round(metrics_escalation * 100, 1),
        "avg_health_score": round(avg_health * 100, 1),
        "avg_agent_health": round(avg_agent_health * 100, 1),
        # Per-department breakdown
        "departments": [
            {
                "id": d.id,
                "name": d.name,
                "slug": d.slug,
                "icon": d.icon,
                "tasks_completed": d.tasks_completed_total,
                "hours_saved": round(d.hours_saved_total, 1),
                "cost_saved": round((d.hours_saved_total or 0) * loaded_rate, 2),
                "automation_coverage": round((d.automation_coverage or 0) * 100, 1),
                "health_score": round((d.health_score or 0) * 100, 1),
                "agent_count": d.agent_count,
            }
            for d in departments
        ],
    }
