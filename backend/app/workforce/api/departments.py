"""
KAEOS Workforce API — Departments
CRUD + lifecycle management for the Department model (workforce/models/core.py).

These are REAL workforce departments (Department-as-a-Service), not
Rule.domain aggregations. Each department owns capabilities, agents,
processes, and has a full deployment lifecycle.
"""
from app.core.tenant import get_tenant_id
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func as sqlfunc
from typing import Optional

from app.core.database import get_db
from app.workforce.models.core import (
    Department, DepartmentStatus, Capability, CapabilityStatus,
    BusinessProcess, DepartmentAgent, WorkforceDeployment,
)

router = APIRouter(prefix="/workforce", tags=["Workforce — Departments"])


async def _resolve_department(db: AsyncSession, dept_ref: str, tenant_id: str) -> Optional[Department]:
    """Resolve a department by DB id OR slug (the frontend routes use slugs like 'hr')."""
    result = await db.execute(
        select(Department)
        .where((Department.id == dept_ref) | (Department.slug == dept_ref))
        .where(Department.tenant_id == tenant_id)
    )
    return result.scalars().first()


@router.get("/departments")
async def list_departments(
    status: Optional[str] = None,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """List all deployed departments for a tenant."""
    q = select(Department).where(Department.tenant_id == tenant_id)
    if status:
        q = q.where(Department.status == status)
    q = q.order_by(Department.created_at.desc())

    result = await db.execute(q)
    departments = result.scalars().all()

    return {
        "total": len(departments),
        "departments": [
            {
                "id": d.id,
                "name": d.name,
                "slug": d.slug,
                "description": d.description,
                "icon": d.icon,
                "status": d.status.value if isinstance(d.status, DepartmentStatus) else d.status,
                "domain_pack_id": d.domain_pack_id,
                "employee_count": d.employee_count,
                "agent_count": d.agent_count,
                "capability_count": d.capability_count,
                "process_count": d.process_count,
                "health_score": d.health_score,
                "automation_coverage": d.automation_coverage,
                "tasks_completed_total": d.tasks_completed_total,
                "hours_saved_total": d.hours_saved_total,
                "connected_systems": d.connected_systems or [],
                "compliance_frameworks": d.compliance_frameworks or [],
                "deployed_at": str(d.deployed_at) if d.deployed_at else None,
                "created_at": str(d.created_at) if d.created_at else None,
            }
            for d in departments
        ],
    }


@router.get("/departments/{dept_id}")
async def get_department(
    dept_id: str,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Get a single department (by id or slug) with capabilities and agents."""
    dept = await _resolve_department(db, dept_id, tenant_id)
    if not dept:
        raise HTTPException(status_code=404, detail="Department not found")

    # Capabilities
    cap_result = await db.execute(
        select(Capability)
        .where(Capability.department_id == dept.id)
        .where(Capability.tenant_id == tenant_id)
        .order_by(Capability.name)
    )
    capabilities = cap_result.scalars().all()

    # Agents
    agent_result = await db.execute(
        select(DepartmentAgent)
        .where(DepartmentAgent.department_id == dept.id)
        .where(DepartmentAgent.tenant_id == tenant_id)
        .order_by(DepartmentAgent.agent_name)
    )
    agents = agent_result.scalars().all()

    # Processes
    proc_result = await db.execute(
        select(BusinessProcess)
        .where(BusinessProcess.department_id == dept.id)
        .where(BusinessProcess.tenant_id == tenant_id)
        .order_by(BusinessProcess.name)
    )
    processes = proc_result.scalars().all()

    return {
        "id": dept.id,
        "name": dept.name,
        "slug": dept.slug,
        "description": dept.description,
        "icon": dept.icon,
        "status": dept.status.value if isinstance(dept.status, DepartmentStatus) else dept.status,
        "domain_pack_id": dept.domain_pack_id,
        "employee_count": dept.employee_count,
        "agent_count": dept.agent_count,
        "capability_count": dept.capability_count,
        "process_count": dept.process_count,
        "health_score": dept.health_score,
        "automation_coverage": dept.automation_coverage,
        "tasks_completed_total": dept.tasks_completed_total,
        "hours_saved_total": dept.hours_saved_total,
        "connected_systems": dept.connected_systems or [],
        "compliance_frameworks": dept.compliance_frameworks or [],
        "deployed_at": str(dept.deployed_at) if dept.deployed_at else None,
        "created_at": str(dept.created_at) if dept.created_at else None,
        "capabilities": [
            {
                "id": c.id,
                "name": c.name,
                "slug": c.slug,
                "description": c.description,
                "icon": c.icon,
                "status": c.status.value if isinstance(c.status, CapabilityStatus) else c.status,
                "automation_pct": c.automation_pct,
                "tasks_completed": c.tasks_completed,
                "active_agents": c.active_agents,
            }
            for c in capabilities
        ],
        "agents": [
            {
                "id": a.id,
                "agent_name": a.agent_name,
                "agent_type": a.agent_type,
                "role_in_department": a.role_in_department,
                "status": a.status,
                "health_score": a.health_score,
                "tasks_handled": a.tasks_handled,
                "last_active_at": str(a.last_active_at) if a.last_active_at else None,
            }
            for a in agents
        ],
        "processes": [
            {
                "id": p.id,
                "name": p.name,
                "slug": p.slug,
                "description": p.description,
                "status": p.status,
                "automation_pct": p.automation_pct,
                "execution_count": p.execution_count,
                "avg_duration_ms": p.avg_duration_ms,
                "success_rate": p.success_rate,
                "sla_hours": p.sla_hours,
            }
            for p in processes
        ],
    }


@router.get("/departments/{dept_id}/capabilities")
async def get_department_capabilities(
    dept_id: str,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Get capabilities for a department (by id or slug) with their processes."""
    dept = await _resolve_department(db, dept_id, tenant_id)
    if not dept:
        raise HTTPException(status_code=404, detail="Department not found")
    dept_id = dept.id
    cap_result = await db.execute(
        select(Capability)
        .where(Capability.department_id == dept_id)
        .where(Capability.tenant_id == tenant_id)
    )
    capabilities = cap_result.scalars().all()

    result = []
    for cap in capabilities:
        proc_result = await db.execute(
            select(BusinessProcess)
            .where(BusinessProcess.capability_id == cap.id)
        )
        procs = proc_result.scalars().all()

        result.append({
            "id": cap.id,
            "name": cap.name,
            "slug": cap.slug,
            "description": cap.description,
            "icon": cap.icon,
            "status": cap.status.value if isinstance(cap.status, CapabilityStatus) else cap.status,
            "automation_pct": cap.automation_pct,
            "tasks_completed": cap.tasks_completed,
            "active_agents": cap.active_agents,
            "processes": [
                {
                    "id": p.id,
                    "name": p.name,
                    "status": p.status,
                    "execution_count": p.execution_count,
                    "success_rate": p.success_rate,
                }
                for p in procs
            ],
        })

    return {"department_id": dept_id, "total": len(result), "capabilities": result}


@router.get("/departments/{dept_id}/agents")
async def get_department_agents(
    dept_id: str,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Get all agents assigned to a department (by id or slug)."""
    dept = await _resolve_department(db, dept_id, tenant_id)
    if not dept:
        raise HTTPException(status_code=404, detail="Department not found")
    dept_id = dept.id
    result = await db.execute(
        select(DepartmentAgent)
        .where(DepartmentAgent.department_id == dept_id)
        .where(DepartmentAgent.tenant_id == tenant_id)
        .order_by(DepartmentAgent.agent_name)
    )
    agents = result.scalars().all()
    return {
        "department_id": dept_id,
        "total": len(agents),
        "agents": [
            {
                "id": a.id,
                "agent_name": a.agent_name,
                "agent_type": a.agent_type,
                "role_in_department": a.role_in_department,
                "persona": a.persona[:200] if a.persona else None,
                "status": a.status,
                "health_score": a.health_score,
                "tasks_handled": a.tasks_handled,
                "skills": a.skills or [],
                "compliance_tags": a.compliance_tags or [],
                "last_active_at": str(a.last_active_at) if a.last_active_at else None,
            }
            for a in agents
        ],
    }


@router.get("/autonomy-trend")
async def autonomy_trend(
    days: int = Query(30, ge=2, le=365),
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Safe autonomy rate per day, derived from real executions.

    The product's whole claim is that it LEARNS - agents earn autonomy as
    confidence rises. Every screen was a snapshot, so that curve was invisible.
    A single number ("57%") is a status; a rising line is the thesis.
    """
    from datetime import datetime, timedelta, timezone as _tz

    from app.models.domain import SkillExecution

    since = datetime.now(_tz.utc) - timedelta(days=days)
    rows = (await db.execute(
        select(SkillExecution.started_at, SkillExecution.status, SkillExecution.hitl_required)
        .where(SkillExecution.tenant_id == tenant_id, SkillExecution.started_at >= since)
    )).all()

    buckets: dict[str, dict[str, int]] = {}
    for started_at, status, hitl in rows:
        if not started_at:
            continue
        day = started_at.date().isoformat()
        b = buckets.setdefault(day, {"total": 0, "autonomous": 0})
        b["total"] += 1
        if status == "SUCCESS_CLEAN" and not hitl:
            b["autonomous"] += 1

    series = [
        {
            "date": day,
            "total": b["total"],
            "autonomous": b["autonomous"],
            "safe_autonomy_rate_pct": round(b["autonomous"] / b["total"] * 100, 1) if b["total"] else None,
        }
        for day, b in sorted(buckets.items())
    ]

    # Direction of travel: compare the two halves of the window rather than
    # first-vs-last day, which is noise on low volume.
    delta = None
    rated = [p for p in series if p["safe_autonomy_rate_pct"] is not None]
    if len(rated) >= 2:
        mid = len(rated) // 2
        first = sum(p["safe_autonomy_rate_pct"] for p in rated[:mid]) / max(mid, 1)
        second = sum(p["safe_autonomy_rate_pct"] for p in rated[mid:]) / max(len(rated) - mid, 1)
        delta = round(second - first, 1)

    return {"days": days, "series": series, "trend_delta_pct": delta}


@router.get("/graduations")
async def autonomy_graduations(
    limit: int = Query(10, ge=1, le=50),
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Skills that crossed the autonomy threshold - the product's aha moment.

    A skill starts below the 0.82 confidence gate (every run needs a human).
    As runs succeed, the Bayesian update raises its confidence. Crossing the
    threshold means it now executes on its own: it EARNED autonomy. That
    moment was recorded and never shown.
    """
    from app.models.domain import Skill

    THRESHOLD = 0.82
    skills = (await db.execute(
        select(Skill).where(Skill.tenant_id == tenant_id)
    )).scalars().all()

    graduated = [
        {
            "skill_id": s.skill_id,
            "department": s.department,
            "confidence": round(float(s.confidence or 0), 3),
            "executions": s.execution_count or 0,
            "success_rate": round(float(s.success_rate or 0), 3),
            "status": "AUTONOMOUS",
        }
        for s in skills
        if (s.confidence or 0) >= THRESHOLD and (s.execution_count or 0) > 0
    ]
    graduated.sort(key=lambda x: (-x["executions"], -x["confidence"]))

    # Skills still earning trust - the pipeline behind the headline.
    earning = [
        {
            "skill_id": s.skill_id,
            "department": s.department,
            "confidence": round(float(s.confidence or 0), 3),
            "executions": s.execution_count or 0,
            "to_threshold": round(THRESHOLD - float(s.confidence or 0), 3),
            "status": "EARNING_TRUST",
        }
        for s in skills
        if (s.confidence or 0) < THRESHOLD and (s.execution_count or 0) > 0
    ]
    earning.sort(key=lambda x: x["to_threshold"])

    return {
        "threshold": THRESHOLD,
        "graduated": graduated[:limit],
        "earning_trust": earning[:limit],
        "graduated_count": len(graduated),
        "earning_count": len(earning),
    }


@router.get("/overview")
async def workforce_overview(
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Enterprise Workforce Overview — aggregate KPIs across all departments."""
    # Departments
    dept_q = await db.execute(
        select(
            sqlfunc.count(Department.id),
            sqlfunc.sum(Department.tasks_completed_total),
            sqlfunc.sum(Department.hours_saved_total),
            sqlfunc.avg(Department.health_score),
            sqlfunc.avg(Department.automation_coverage),
        )
        .where(Department.tenant_id == tenant_id)
        .where(Department.status == DepartmentStatus.ACTIVE)
    )
    dept_row = dept_q.one_or_none()

    active_depts = dept_row[0] if dept_row else 0
    total_tasks = int(dept_row[1] or 0) if dept_row else 0
    avg_health = float(dept_row[3] or 0) if dept_row else 0

    # Fleet counts come from the SAME source the department cards render
    # (the per-department rollups). Counting the detail tables here reported
    # 0 agents on a dashboard whose own cards listed dozens - the classic
    # "two sources, one truth" contradiction.
    rollup_q = await db.execute(
        select(
            sqlfunc.sum(Department.agent_count),
            sqlfunc.sum(Department.capability_count),
            sqlfunc.sum(Department.process_count),
        )
        .where(Department.tenant_id == tenant_id)
        .where(Department.status == DepartmentStatus.ACTIVE)
    )
    rollup = rollup_q.one_or_none()
    active_agents = int(rollup[0] or 0) if rollup else 0
    active_capabilities = int(rollup[1] or 0) if rollup else 0
    active_processes = int(rollup[2] or 0) if rollup else 0

    # Safe autonomy rate: the share of real executions that completed WITHOUT
    # a human gate. Derived from SkillExecution rows - not a stored guess.
    # (`automation_coverage` was seeded 0.0 for every department, which is why
    # the dashboard tile read a permanent "0%".)
    from app.models.domain import SkillExecution
    exec_q = await db.execute(
        select(SkillExecution.status, SkillExecution.hitl_required)
        .where(SkillExecution.tenant_id == tenant_id)
    )
    execs = exec_q.all()
    total_execs = len(execs)
    autonomous = [e for e in execs if e[0] == "SUCCESS_CLEAN" and not e[1]]
    safe_autonomy_rate = (
        round(len(autonomous) / total_execs * 100, 1) if total_execs else None
    )

    # Active deployments
    deploy_q = await db.execute(
        select(sqlfunc.count(WorkforceDeployment.id))
        .where(WorkforceDeployment.tenant_id == tenant_id)
    )
    total_deployments = deploy_q.scalar() or 0

    return {
        "departments_active": active_depts,
        "agents_active": active_agents,
        "processes_active": active_processes,
        "capabilities_active": active_capabilities,
        "total_deployments": total_deployments,
        "tasks_completed": total_tasks,
        "avg_health_score": round(avg_health * 100, 1),
        # The north-star metric: real executions, no human gate, from the DB.
        "safe_autonomy_rate_pct": safe_autonomy_rate,
        "total_executions": total_execs,
        "autonomous_executions": len(autonomous),
        # `hours_saved` used to be tasks x 0.5 - a number with no basis. It
        # needs a per-skill human baseline and loaded hourly rate (tenant
        # inputs), so it is null rather than invented. Same rule as /billing.
        "hours_saved": None,
        "hours_saved_note": (
            "Requires a human-baseline duration and loaded hourly rate per skill "
            "(tenant inputs). Not estimated."
        ),
    }
