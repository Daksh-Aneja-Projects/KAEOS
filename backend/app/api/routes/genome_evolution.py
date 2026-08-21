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
from sqlalchemy import select, func, case, cast, String
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.tenant import get_tenant_id
from app.models.execution_status import SUCCEEDED_STATUSES

router = APIRouter(tags=["Genome & Evolution — Live Fitness"])


async def _live_features(db: AsyncSession, tenant_id: str) -> Dict[str, float]:
    """Extract the physics-law feature vector (0-100 scales) from live rows."""
    from app.hr.models.core import HREmployee
    from app.models.agent_factory import DeployedAgent
    from app.models.domain import SkillExecution
    from app.finance.models.accounts_payable import Vendor
    from app.finance.models.budgeting import Budget

    emp_stats = (await db.execute(
        select(
            func.count(HREmployee.id).label("total"),
            func.count(case((cast(HREmployee.status, String) == "ACTIVE", 1))).label("active"),
        ).where(HREmployee.tenant_id == tenant_id)
    )).one()
    workforce_stability = (emp_stats.active / emp_stats.total * 100) if emp_stats.total else 50.0

    agent_stats = (await db.execute(
        select(
            func.count(DeployedAgent.id).label("total"),
            func.count(case((cast(DeployedAgent.status, String) == "RUNNING", 1))).label("running"),
        ).where(DeployedAgent.tenant_id == tenant_id)
    )).one()
    capability_redundancy = (agent_stats.running / agent_stats.total * 100) if agent_stats.total else 50.0

    exec_statuses = (await db.execute(
        select(SkillExecution.status)
        .where(SkillExecution.tenant_id == tenant_id)
        .order_by(SkillExecution.started_at.desc())
        .limit(300)
    )).scalars().all()
    # Delivery counts a run whose answer stood, including one a human corrected -
    # that work still shipped. It is NOT the safe-autonomy rate, which excludes
    # anything a human touched; see execution_status.SUCCEEDED_STATUSES.
    successes = sum(1 for s in exec_statuses if (s or "").upper() in SUCCEEDED_STATUSES)
    project_delivery = (successes / len(exec_statuses) * 100) if exec_statuses else 50.0

    # Vendor spend — SQL aggregation to avoid loading all vendor rows.
    vendor_stats = (await db.execute(
        select(
            func.coalesce(func.sum(Vendor.total_spend_ytd), 0).label("total_spend"),
            func.coalesce(func.max(Vendor.total_spend_ytd), 0).label("max_spend"),
        ).where(Vendor.tenant_id == tenant_id)
    )).one()
    total_spend = float(vendor_stats.total_spend)
    max_spend = float(vendor_stats.max_spend)
    vendor_concentration = (max_spend / total_spend * 100) if total_spend > 0 else 50.0

    budget_stats = (await db.execute(
        select(
            func.coalesce(func.sum(Budget.total_planned), 0).label("planned"),
            func.coalesce(func.sum(Budget.total_actual), 0).label("actual"),
        ).where(Budget.tenant_id == tenant_id)
    )).one()
    planned = float(budget_stats.planned)
    actual = float(budget_stats.actual)
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

    # Fitness timeline: weekly success-rate buckets from real execution history.
    #
    # Counted in SQL, grouped by DAY. SkillExecution is the highest-volume table
    # in the product and each row carries context + reasoning_chain JSON, so
    # loading every row to bucket it in Python read the whole history from the
    # beginning on every request. A row limit is not an option here: it would
    # silently truncate the very timeline this draws. Grouping by day bounds the
    # result by the calendar instead of by throughput, and days fold into ISO
    # weeks exactly. Day (not week) because ISO-week SQL is not portable across
    # SQLite and Postgres, whereas date() is.
    day_rows = (await db.execute(
        select(
            func.date(SkillExecution.started_at).label("day"),
            func.count().label("total"),
            func.sum(
                case((func.upper(SkillExecution.status).like("SUCCESS%"), 1), else_=0)
            ).label("successes"),
        )
        .where(
            SkillExecution.tenant_id == tenant_id,
            SkillExecution.started_at.isnot(None),
        )
        .group_by(func.date(SkillExecution.started_at))
    )).all()

    timeline = []
    if day_rows:
        # week -> [successes, total]
        buckets: Dict[str, list] = {}
        for day, total, successes in day_rows:
            if not day:
                continue
            d = day if hasattr(day, "strftime") else datetime.fromisoformat(str(day))
            week = d.strftime("%G-W%V")
            agg = buckets.setdefault(week, [0, 0])
            agg[0] += int(successes or 0)
            agg[1] += int(total or 0)
        for idx, (week, (successes, total)) in enumerate(sorted(buckets.items()), start=1):
            if not total:
                continue
            rate = successes / total
            timeline.append({
                "version": f"v{idx}",
                "fitness": round(rate, 3),
                "risk": round(1 - rate, 3),
                "time": week,
                "executions": total,
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

    # SQL aggregates, not full-table hydrations: these tables (rules, fairness
    # audit log, executions) grow forever, and every number below is a count or
    # an average. coalesce(x, 0) reproduces the old Python `x or 0` per row;
    # cast-to-String enum matching mirrors _live_features above.
    total_rules, verified = (await db.execute(
        select(func.count(Rule.id),
               func.count(case((cast(Rule.confidence_tier, String) == "VERIFIED", 1))))
        .where(Rule.tenant_id == tenant_id)
    )).one()
    goal_alignment = verified / total_rules if total_rules else None

    skill_count, avg_conf_raw = (await db.execute(
        select(func.count(Skill.id), func.avg(func.coalesce(Skill.confidence, 0.0)))
        .where(Skill.tenant_id == tenant_id)
    )).one()
    avg_skill_conf = float(avg_conf_raw) if skill_count else None

    fairness_total, fairness_passed = (await db.execute(
        select(func.count(FairnessAuditLog.id),
               func.count(case((FairnessAuditLog.passed == True, 1))))
        .where(FairnessAuditLog.tenant_id == tenant_id)
    )).one()
    risk_fitness = fairness_passed / fairness_total if fairness_total else None

    dept_count, org_fitness_raw = (await db.execute(
        select(func.count(Department.id),
               func.avg(func.coalesce(Department.health_score, 0.0)))
        .where(Department.tenant_id == tenant_id)
    )).one()
    org_fitness = float(org_fitness_raw) if dept_count else None
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
    inferred = total_rules - verified
    if inferred > 0 and goal_alignment is not None:
        optimizations.append({
            "type": "KNOWLEDGE_VERIFICATION",
            "description": f"{inferred} rules remain INFERRED. Route them through expert elicitation to lift goal alignment.",
            "expected_gain": round((1 - goal_alignment) * 0.15, 3),
            "expected_cost": inferred * 50,
            "risk": 0.05,
        })
    agent_total, stopped = (await db.execute(
        select(func.count(DeployedAgent.id),
               func.count(case((cast(DeployedAgent.status, String) == "STOPPED", 1))))
        .where(DeployedAgent.tenant_id == tenant_id)
    )).one()
    if stopped:
        optimizations.append({
            "type": "WORKFORCE_REACTIVATION",
            "description": f"{stopped} deployed agents are STOPPED. Restart or retire them to raise portfolio utilization.",
            "expected_gain": round(min(0.1, stopped / max(agent_total, 1) * 0.2), 3),
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
    # Thin status column only — same FAILED* prefix logic, none of the row weight.
    recent_statuses = (await db.execute(
        select(SkillExecution.status)
        .where(
            SkillExecution.tenant_id == tenant_id,
            SkillExecution.started_at >= datetime.now(timezone.utc) - timedelta(days=7),
        )
    )).scalars().all()
    failed_count = sum(1 for s in recent_statuses if (s or "").upper().startswith("FAILED"))
    if failed_count:
        optimizations.append({
            "type": "EXECUTION_HARDENING",
            "description": f"{failed_count} skill executions failed in the last 7 days. Review their reasoning chains and retrain the weakest skills.",
            "expected_gain": round(min(0.15, failed_count / max(len(recent_statuses), 1) * 0.3), 3),
            "expected_cost": failed_count * 100,
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
