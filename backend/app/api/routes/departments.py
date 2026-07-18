"""KAEOS — Departments API (Department-centric views)"""
from app.core.tenant import get_tenant_id
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func as sqlfunc
from app.core.database import get_db
from app.models.domain import Rule, Skill, Workflow

router = APIRouter(prefix="/departments", tags=["Departments"])


@router.get("")
async def list_departments(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    """
    List all departments derived from Rule domains and Skill departments.
    No hardcoded department names — fully dynamic from DB.
    """
    # All aggregates below are scoped to the caller's tenant.
    # Get department data from Rules
    rule_depts = await db.execute(
        select(
            Rule.domain,
            sqlfunc.count(Rule.id).label("rule_count"),
            sqlfunc.avg(Rule.confidence_scalar).label("avg_confidence"),
            sqlfunc.count(Rule.id).filter(Rule.is_executable == True).label("exec_count"),
        )
        .where(Rule.tenant_id == tenant_id, Rule.is_archived == False, Rule.domain.isnot(None))
        .group_by(Rule.domain)
    )
    rule_rows = rule_depts.all()

    # Get skill counts per department
    skill_depts = await db.execute(
        select(
            Skill.department,
            sqlfunc.count(Skill.id).label("skill_count"),
            sqlfunc.avg(Skill.success_rate).label("avg_success"),
        )
        .where(Skill.tenant_id == tenant_id, Skill.department.isnot(None))
        .group_by(Skill.department)
    )
    skill_map = {row[0]: {"skill_count": row[1], "avg_success": round(row[2] or 0, 4)} for row in skill_depts.all()}

    # Get workflow counts per department
    wf_depts = await db.execute(
        select(
            Workflow.department,
            sqlfunc.count(Workflow.id).label("wf_count"),
        )
        .where(Workflow.tenant_id == tenant_id, Workflow.department.isnot(None))
        .group_by(Workflow.department)
    )
    wf_map = {row[0]: row[1] for row in wf_depts.all()}

    departments = []
    for domain, rule_count, avg_conf, exec_count in rule_rows:
        if not domain:
            continue
        skill_data = skill_map.get(domain, {"skill_count": 0, "avg_success": 0.0})
        coverage = round(min(1.0, rule_count / 20.0), 4)
        avg_confidence = round(avg_conf or 0.0, 4)

        # Status: green if coverage > 70% and confidence > 0.7
        status = "active"
        if coverage >= 0.7 and avg_confidence >= 0.7:
            status = "healthy"
        elif coverage < 0.3 or avg_confidence < 0.4:
            status = "needs_attention"

        departments.append({
            "id": domain,
            "name": domain.replace("_", " ").title(),
            "rule_count": rule_count,
            "executable_rules": exec_count,
            "skill_count": skill_data["skill_count"],
            "workflow_count": wf_map.get(domain, 0),
            "avg_confidence": avg_confidence,
            "avg_success_rate": skill_data["avg_success"],
            "coverage": coverage,
            "status": status,
        })

    # Sort by rule_count descending
    departments.sort(key=lambda d: d["rule_count"], reverse=True)

    return {
        "total": len(departments),
        "departments": departments,
    }


@router.get("/{dept_id}/capabilities")
async def get_department_capabilities(dept_id: str, tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    """
    Get capabilities (skills) for a specific department.
    Renders whatever the backend has — no placeholders.
    """
    # Fetch skills for this department — scoped to the caller's tenant.
    skills_result = await db.execute(
        select(Skill)
        .where(Skill.tenant_id == tenant_id, Skill.department == dept_id)
        .order_by(Skill.confidence.desc())
    )
    skills = skills_result.scalars().all()

    # Also check by domain (in case department field isn't set but domain matches)
    if not skills:
        skills_result = await db.execute(
            select(Skill)
            .where(Skill.tenant_id == tenant_id, Skill.domain == dept_id)
            .order_by(Skill.confidence.desc())
        )
        skills = skills_result.scalars().all()

    capabilities = []
    for s in skills:
        capabilities.append({
            "id": s.id,
            "skill_id": s.skill_id,
            "name": s.skill_id.replace("_", " ").replace("-", " ").title(),
            "domain": s.domain,
            "version": s.version,
            "status": s.status,
            "confidence": s.confidence,
            "confidence_tier": s.confidence_tier.value if hasattr(s.confidence_tier, 'value') else str(s.confidence_tier) if s.confidence_tier else None,
            "execution_count": s.execution_count,
            "success_rate": s.success_rate,
            "mcp_tool_bindings": s.mcp_tool_bindings or [],
            "compliance_tags": s.compliance_tags or [],
        })

    # Department-level aggregate stats
    total_executions = sum(c["execution_count"] for c in capabilities)
    avg_confidence = round(
        sum(c["confidence"] for c in capabilities) / max(len(capabilities), 1), 4
    )
    avg_success = round(
        sum(c["success_rate"] for c in capabilities) / max(len(capabilities), 1), 4
    )

    return {
        "department": dept_id,
        "department_name": dept_id.replace("_", " ").title(),
        "total_capabilities": len(capabilities),
        "total_executions": total_executions,
        "avg_confidence": avg_confidence,
        "avg_success_rate": avg_success,
        "capabilities": capabilities,
    }
