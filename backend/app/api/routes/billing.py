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
from sqlalchemy import func, select
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
    events = (await db.execute(
        select(CostEvent).where(CostEvent.tenant_id == tenant_id)
    )).scalars().all()

    exec_count = await db.scalar(
        select(func.count(SkillExecution.id)).where(SkillExecution.tenant_id == tenant_id)
    ) or 0

    total_cost = sum(e.cost_usd or 0 for e in events)
    input_tokens = sum(e.input_tokens or 0 for e in events)
    output_tokens = sum(e.output_tokens or 0 for e in events)

    # Per-tier and per-model attribution — what the tenant is actually paying for.
    by_tier: dict = {}
    by_model: dict = {}
    for e in events:
        tier = by_tier.setdefault(e.model_tier or "unknown", {"calls": 0, "cost_usd": 0.0, "tokens": 0})
        tier["calls"] += 1
        tier["cost_usd"] = round(tier["cost_usd"] + (e.cost_usd or 0), 4)
        tier["tokens"] += e.total_tokens or 0

        model = by_model.setdefault(e.model_name or "unknown", {"calls": 0, "cost_usd": 0.0})
        model["calls"] += 1
        model["cost_usd"] = round(model["cost_usd"] + (e.cost_usd or 0), 4)

    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    recent = [e for e in events if e.timestamp and e.timestamp.replace(tzinfo=timezone.utc) >= cutoff]

    return {
        "tenant_id": tenant_id,
        "metered_calls": len(events),
        "total_executions": exec_count,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "total_cost_usd": round(total_cost, 4),
        "cost_last_30d_usd": round(sum(e.cost_usd or 0 for e in recent), 4),
        "avg_cost_per_call_usd": round(total_cost / len(events), 6) if events else None,
        "by_tier": by_tier,
        "by_model": by_model,
        "currency": "USD",
        # No metering yet means no bill — say so rather than inventing one.
        "metering_active": bool(events),
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
    executions = (await db.execute(
        select(SkillExecution).where(SkillExecution.tenant_id == tenant_id)
    )).scalars().all()

    events = (await db.execute(
        select(CostEvent).where(CostEvent.tenant_id == tenant_id)
    )).scalars().all()

    total = len(executions)
    autonomous = [e for e in executions if not e.hitl_required]
    succeeded = [e for e in executions if (e.status or "").upper().startswith("SUCCESS")]
    machine_seconds = sum((e.duration_ms or 0) for e in executions) / 1000.0
    total_cost = sum(e.cost_usd or 0 for e in events)

    return {
        "tenant_id": tenant_id,
        "total_executions": total,
        "autonomous_executions": len(autonomous),
        # The metric that matters: work completed without a human in the loop.
        "safe_autonomy_rate_pct": round(len(autonomous) / total * 100, 1) if total else None,
        "success_rate_pct": round(len(succeeded) / total * 100, 1) if total else None,
        "machine_time_hours": round(machine_seconds / 3600, 3),
        "total_cost_usd": round(total_cost, 4),
        "cost_per_successful_execution_usd": (
            round(total_cost / len(succeeded), 6) if succeeded and total_cost else None
        ),
        "total_hours_saved": None,
        "total_cost_reduction": None,
        "note": (
            "hours_saved and cost_reduction require a human-baseline duration and loaded "
            "hourly rate per skill, which are tenant inputs. They are null rather than estimated."
        ),
        "currency": "USD",
    }
