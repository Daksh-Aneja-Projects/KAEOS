"""
Billing & Usage — computed from recorded cost events, not invented constants.

Previously this router multiplied an execution count by a hardcoded
$0.015/execution and asserted "0.5 hours saved per execution". Those numbers
were fabricated. Everything below is derived from CostEvent rows written by the
cost governor, with real token counts; where a figure genuinely cannot be
derived it is returned as null and labelled, rather than guessed.
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select, case, literal_column
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.tenant import get_tenant_id
from app.models.domain import SkillExecution
from app.models.infrastructure import CostEvent

router = APIRouter(prefix="/billing", tags=["Billing & Usage"])


@router.get("/usage")
async def get_tenant_usage(
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Actual metered usage for this tenant, from recorded cost events."""
    # Aggregate in SQL — never load all rows into Python.
    totals = (await db.execute(
        select(
            func.count(CostEvent.id).label("call_count"),
            func.coalesce(func.sum(CostEvent.cost_usd), 0).label("total_cost"),
            func.coalesce(func.sum(CostEvent.input_tokens), 0).label("input_tokens"),
            func.coalesce(func.sum(CostEvent.output_tokens), 0).label("output_tokens"),
            func.coalesce(func.sum(CostEvent.total_tokens), 0).label("total_tokens"),
        ).where(CostEvent.tenant_id == tenant_id)
    )).one()

    exec_count = await db.scalar(
        select(func.count(SkillExecution.id)).where(SkillExecution.tenant_id == tenant_id)
    ) or 0

    # Per-tier breakdown (SQL GROUP BY).
    tier_rows = (await db.execute(
        select(
            func.coalesce(CostEvent.model_tier, literal_column("'unknown'")).label("tier"),
            func.count(CostEvent.id).label("calls"),
            func.coalesce(func.sum(CostEvent.cost_usd), 0).label("cost_usd"),
            func.coalesce(func.sum(CostEvent.total_tokens), 0).label("tokens"),
        ).where(CostEvent.tenant_id == tenant_id)
        .group_by(CostEvent.model_tier)
    )).all()

    # Per-model breakdown.
    model_rows = (await db.execute(
        select(
            func.coalesce(CostEvent.model_name, literal_column("'unknown'")).label("model"),
            func.count(CostEvent.id).label("calls"),
            func.coalesce(func.sum(CostEvent.cost_usd), 0).label("cost_usd"),
        ).where(CostEvent.tenant_id == tenant_id)
        .group_by(CostEvent.model_name)
    )).all()

    # Last 30 days cost.
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    cost_30d = await db.scalar(
        select(func.coalesce(func.sum(CostEvent.cost_usd), 0))
        .where(CostEvent.tenant_id == tenant_id, CostEvent.timestamp >= cutoff)
    ) or 0

    by_tier = {r.tier: {"calls": r.calls, "cost_usd": round(float(r.cost_usd), 4), "tokens": r.tokens} for r in tier_rows}
    by_model = {r.model: {"calls": r.calls, "cost_usd": round(float(r.cost_usd), 4)} for r in model_rows}

    call_count = totals.call_count
    total_cost = float(totals.total_cost)

    return {
        "tenant_id": tenant_id,
        "metered_calls": call_count,
        "total_executions": exec_count,
        "input_tokens": totals.input_tokens,
        "output_tokens": totals.output_tokens,
        "total_tokens": totals.total_tokens,
        "total_cost_usd": round(total_cost, 4),
        "cost_last_30d_usd": round(float(cost_30d), 4),
        "avg_cost_per_call_usd": round(total_cost / call_count, 6) if call_count else None,
        "by_tier": by_tier,
        "by_model": by_model,
        "currency": "USD",
        "metering_active": call_count > 0,
    }


@router.get("/roi")
async def get_tenant_roi(
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """
    ROI grounded in measured execution time.

    Hours saved is the one figure that needs a human baseline — how long the
    same task takes a person. That baseline is a tenant input, not something
    KAEOS can measure, so it is returned as null with an explicit note unless
    configured. What IS measured: how much machine time and money the work
    actually consumed, and the automation rate.
    """
    # Aggregate executions in SQL — never load all rows.
    exec_stats = (await db.execute(
        select(
            func.count(SkillExecution.id).label("total"),
            func.count(case((SkillExecution.hitl_required == False, 1))).label("autonomous"),
            func.count(case((func.upper(SkillExecution.status).like("SUCCESS%"), 1))).label("succeeded"),
            func.coalesce(func.sum(SkillExecution.duration_ms), 0).label("total_ms"),
        ).where(SkillExecution.tenant_id == tenant_id)
    )).one()

    total_cost = await db.scalar(
        select(func.coalesce(func.sum(CostEvent.cost_usd), 0))
        .where(CostEvent.tenant_id == tenant_id)
    ) or 0

    total = exec_stats.total
    autonomous = exec_stats.autonomous
    succeeded = exec_stats.succeeded
    machine_seconds = float(exec_stats.total_ms) / 1000.0
    total_cost = float(total_cost)

    return {
        "tenant_id": tenant_id,
        "total_executions": total,
        "autonomous_executions": autonomous,
        "safe_autonomy_rate_pct": round(autonomous / total * 100, 1) if total else None,
        "success_rate_pct": round(succeeded / total * 100, 1) if total else None,
        "machine_time_hours": round(machine_seconds / 3600, 3),
        "total_cost_usd": round(total_cost, 4),
        "cost_per_successful_execution_usd": (
            round(total_cost / succeeded, 6) if succeeded and total_cost else None
        ),
        "total_hours_saved": None,
        "total_cost_reduction": None,
        "note": (
            "hours_saved and cost_reduction require a human-baseline duration and loaded "
            "hourly rate per skill, which are tenant inputs. They are null rather than estimated."
        ),
        "currency": "USD",
    }
