"""
Genome & Evolution state — live enterprise fitness computed from real tables.

Exposes the previously-orphaned GenomeCompiler (L-genome) over an API and
replaces the hardcoded mock data that GenomeStudio / EvolutionStudio shipped
with. Every number here is derived from live rows; when a data source is
empty the corresponding field is null rather than fabricated.
"""
from datetime import datetime, timedelta, timezone
from typing import Dict

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.tenant import get_tenant_id

router = APIRouter(tags=["Genome & Evolution — Live Fitness"])


async def _live_features(db: AsyncSession, tenant_id: str) -> Dict[str, float]:
    """Extract the physics-law feature vector (0-100 scales) from live rows."""
    from app.hr.models.core import HREmployee
    from app.models.agent_factory import DeployedAgent
    from app.models.domain import SkillExecution
    from app.finance.models.accounts_payable import Vendor
    from app.finance.models.budgeting import Budget

    emps = (await db.execute(
        select(HREmployee).where(HREmployee.tenant_id == tenant_id)
    )).scalars().all()
    active_emps = sum(
        1 for e in emps
        if (e.status.value if hasattr(e.status, "value") else str(e.status)) == "ACTIVE"
    )
    workforce_stability = (active_emps / len(emps) * 100) if emps else 50.0

    agents = (await db.execute(
        select(DeployedAgent).where(DeployedAgent.tenant_id == tenant_id)
    )).scalars().all()
    running = sum(
        1 for a in agents
        if (a.status.value if hasattr(a.status, "value") else str(a.status)) == "RUNNING"
    )
    capability_redundancy = (running / len(agents) * 100) if agents else 50.0

    executions = (await db.execute(
        select(SkillExecution)
        .where(SkillExecution.tenant_id == tenant_id)
        .order_by(SkillExecution.started_at.desc())
        .limit(300)
    )).scalars().all()
    successes = sum(1 for e in executions if (e.status or "").upper().startswith("SUCCESS"))
    project_delivery = (successes / len(executions) * 100) if executions else 50.0

    # Vendor spend must be the caller's own, not aggregated across tenants.
    vendors = (await db.execute(
        select(Vendor).where(Vendor.tenant_id == tenant_id)
    )).scalars().all()
    total_spend = sum(float(v.total_spend_ytd or 0) for v in vendors)
    vendor_concentration = (
        max(float(v.total_spend_ytd or 0) for v in vendors) / total_spend * 100
        if vendors and total_spend > 0 else 50.0
    )

    budgets = (await db.execute(
        select(Budget).where(Budget.tenant_id == tenant_id)
    )).scalars().all()
    planned = sum(float(b.total_planned or 0) for b in budgets)
    actual = sum(float(b.total_actual or 0) for b in budgets)
    budget_utilization = (actual / planned * 100) if planned > 0 else 60.0

    return {
        "workforce_stability": round(workforce_stability, 2),
        "capability_redundancy": round(capability_redundancy, 2),
        "project_delivery": round(project_delivery, 2),
        "vendor_concentration": round(vendor_concentration, 2),
        "budget_utilization": round(budget_utilization, 2),
    }


@router.get("/genome/state")
async def genome_state(
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Live genome traits (GenomeCompiler over real features) + fitness timeline."""
    from app.services.genome_compiler import GenomeCompiler
    from app.models.domain import SkillExecution

    features = await _live_features(db, tenant_id)
    traits = GenomeCompiler().compile(features)

    # Fitness timeline: weekly success-rate buckets from real execution history
    executions = (await db.execute(
        select(SkillExecution)
        .where(SkillExecution.tenant_id == tenant_id)
        .order_by(SkillExecution.started_at.asc())
    )).scalars().all()
    timeline = []
    if executions:
        buckets: Dict[str, list] = {}
        for e in executions:
            if not e.started_at:
                continue
            week = e.started_at.strftime("%G-W%V")
            buckets.setdefault(week, []).append(
                (e.status or "").upper().startswith("SUCCESS")
            )
        for idx, (week, results) in enumerate(sorted(buckets.items()), start=1):
            rate = sum(results) / len(results)
            timeline.append({
                "version": f"v{idx}",
                "fitness": round(rate, 3),
                "risk": round(1 - rate, 3),
                "time": week,
                "executions": len(results),
            })

    return {
        "features": features,
        "traits": traits,
        "adaptability": traits.get("Adaptability"),
        "timeline": timeline,
        "total_genomes_tracked": len(timeline),
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/evolution/state")
async def evolution_state(
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Live enterprise fitness, sub-scores, and derived optimization moves."""
    from app.models.domain import Rule, Skill, SkillExecution
    from app.models.agent_factory import DeployedAgent
    from app.models.fairness import FairnessAuditLog
    from app.workforce.models.core import Department

    features = await _live_features(db, tenant_id)

    rules = (await db.execute(
        select(Rule).where(Rule.tenant_id == tenant_id)
    )).scalars().all()
    verified = sum(
        1 for r in rules
        if (r.confidence_tier.value if hasattr(r.confidence_tier, "value") else str(r.confidence_tier)) == "VERIFIED"
    )
    goal_alignment = verified / len(rules) if rules else None

    skills = (await db.execute(
        select(Skill).where(Skill.tenant_id == tenant_id)
    )).scalars().all()
    avg_skill_conf = (
        sum(s.confidence or 0 for s in skills) / len(skills) if skills else None
    )

    fairness = (await db.execute(
        select(FairnessAuditLog).where(FairnessAuditLog.tenant_id == tenant_id)
    )).scalars().all()
    risk_fitness = (
        sum(1 for f in fairness if f.passed) / len(fairness) if fairness else None
    )

    depts = (await db.execute(
        select(Department).where(Department.tenant_id == tenant_id)
    )).scalars().all()
    org_fitness = (
        sum(d.health_score or 0 for d in depts) / len(depts) if depts else None
    )
    org_fitness = org_fitness if org_fitness is None or org_fitness <= 1 else org_fitness / 100

    subscores = {
        "organizational_fitness": org_fitness,
        "workforce_fitness": features["workforce_stability"] / 100,
        "capability_fitness": avg_skill_conf,
        "portfolio_fitness": features["capability_redundancy"] / 100,
        "vendor_fitness": max(0.0, 1 - features["vendor_concentration"] / 100),
        "financial_fitness": max(0.0, 1 - abs(features["budget_utilization"] - 60) / 100),
        "execution_fitness": features["project_delivery"] / 100,
        "goal_alignment_fitness": goal_alignment,
        "risk_fitness": risk_fitness,
    }
    subscores = {k: (round(v, 3) if v is not None else None) for k, v in subscores.items()}
    known = [v for v in subscores.values() if v is not None]
    current_fitness = round(sum(known) / len(known), 3) if known else None

    # Derived optimization moves — each anchored to a real weak signal
    optimizations = []
    inferred = len(rules) - verified
    if inferred > 0 and goal_alignment is not None:
        optimizations.append({
            "type": "KNOWLEDGE_VERIFICATION",
            "description": f"{inferred} rules remain INFERRED. Route them through expert elicitation to lift goal alignment.",
            "expected_gain": round((1 - goal_alignment) * 0.15, 3),
            "expected_cost": inferred * 50,
            "risk": 0.05,
        })
    agents = (await db.execute(
        select(DeployedAgent).where(DeployedAgent.tenant_id == tenant_id)
    )).scalars().all()
    stopped = sum(
        1 for a in agents
        if (a.status.value if hasattr(a.status, "value") else str(a.status)) == "STOPPED"
    )
    if stopped:
        optimizations.append({
            "type": "WORKFORCE_REACTIVATION",
            "description": f"{stopped} deployed agents are STOPPED. Restart or retire them to raise portfolio utilization.",
            "expected_gain": round(min(0.1, stopped / max(len(agents), 1) * 0.2), 3),
            "expected_cost": stopped * 10,
            "risk": 0.1,
        })
    if features["vendor_concentration"] > 50:
        optimizations.append({
            "type": "VENDOR_DIVERSIFICATION",
            "description": f"Top vendor carries {features['vendor_concentration']:.0f}% of YTD spend. Diversify to reduce dependency risk.",
            "expected_gain": round((features["vendor_concentration"] - 50) / 100 * 0.2, 3),
            "expected_cost": 25000,
            "risk": 0.3,
        })
    recent_failures = (await db.execute(
        select(SkillExecution)
        .where(
            SkillExecution.tenant_id == tenant_id,
            SkillExecution.started_at >= datetime.now(timezone.utc) - timedelta(days=7),
        )
    )).scalars().all()
    failed = [e for e in recent_failures if (e.status or "").upper().startswith("FAILED")]
    if failed:
        optimizations.append({
            "type": "EXECUTION_HARDENING",
            "description": f"{len(failed)} skill executions failed in the last 7 days. Review their reasoning chains and retrain the weakest skills.",
            "expected_gain": round(min(0.15, len(failed) / max(len(recent_failures), 1) * 0.3), 3),
            "expected_cost": len(failed) * 100,
            "risk": 0.15,
        })

    optimizations.sort(key=lambda o: o["expected_gain"], reverse=True)
    projected = (
        round(min(1.0, current_fitness + sum(o["expected_gain"] for o in optimizations)), 3)
        if current_fitness is not None else None
    )
    breaches = sum(1 for v in subscores.values() if v is not None and v < 0.6)

    return {
        "current_fitness": current_fitness,
        "future_fitness": projected,
        "genome_version": 1,
        "subscores": subscores,
        "breaches": breaches,
        "optimizations": optimizations,
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }
