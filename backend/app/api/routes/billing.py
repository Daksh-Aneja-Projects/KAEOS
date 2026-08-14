"""
Billing & Usage — computed from recorded cost events, not invented constants.

Previously this router multiplied an execution count by a hardcoded
$0.015/execution and asserted "0.5 hours saved per execution". Those numbers
were fabricated. Everything below is derived from CostEvent rows written by the
cost governor, with real token counts; where a figure genuinely cannot be
derived it is returned as null and labelled, rather than guessed.
"""
from decimal import Decimal
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request, HTTPException
from sqlalchemy import func, select, case, literal_column
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.tenant import get_tenant_id, get_tenant
from app.models.domain import SkillExecution
from app.models.infrastructure import CostEvent

router = APIRouter(prefix="/billing", tags=["Billing & Usage"])

# /roi reports lifetime cost and machine time, so its safe-autonomy figure is
# computed over the same lifetime scope. compute_safe_autonomy takes a window in
# days; this is that window widened past any real tenant history.
_ALL_TIME_DAYS = 36500


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

    Hours saved is the one figure that needs a human baseline: how long the
    same task takes a person. That baseline is a tenant input, not something
    KAEOS can measure, so it is returned as null with an explicit note unless
    configured. What IS measured: how much machine time and money the work
    actually consumed, and the safe-autonomy rate.

    The safe-autonomy rate comes from the ONE canonical implementation in
    app/services/safe_autonomy.py. This route used to compute its own version
    from `hitl_required == False` alone, which counted an unattended FAILURE as
    safe autonomy and so reported a materially higher number than every other
    surface. A north-star metric with two definitions is worse than no metric.
    """
    # Aggregate executions in SQL — never load all rows.
    exec_stats = (await db.execute(
        select(
            func.count(SkillExecution.id).label("total"),
            func.count(case((SkillExecution.hitl_required == False, 1))).label("unattended"),
            func.count(case((func.upper(SkillExecution.status).like("SUCCESS%"), 1))).label("succeeded"),
            func.coalesce(func.sum(SkillExecution.duration_ms), 0).label("total_ms"),
        ).where(SkillExecution.tenant_id == tenant_id)
    )).one()

    total_cost = await db.scalar(
        select(func.coalesce(func.sum(CostEvent.cost_usd), 0))
        .where(CostEvent.tenant_id == tenant_id)
    ) or 0

    total = exec_stats.total
    unattended = exec_stats.unattended
    succeeded = exec_stats.succeeded
    machine_seconds = float(exec_stats.total_ms) / 1000.0
    total_cost = float(total_cost)

    # Canonical north-star, over the same all-time scope as the cost figures
    # beside it, so every number in this payload describes one population.
    from app.services.safe_autonomy import compute_safe_autonomy
    sar = await compute_safe_autonomy(db, tenant_id, days=_ALL_TIME_DAYS)
    sar_rate = sar.get("safe_autonomy_rate")

    # Value delivered is null unless a per-skill human baseline is configured.
    # KAEOS never invents a dollar figure: value is only computed for skills the
    # tenant has told us how long a person takes and what that person costs.
    value_delivered, value_note, skills_priced = await _value_delivered(db, tenant_id)

    return {
        "tenant_id": tenant_id,
        "total_executions": total,
        "safe_autonomy_rate_pct": round(sar_rate * 100, 1) if sar_rate is not None else None,
        "safe_autonomy_window_days": _ALL_TIME_DAYS,
        "safe_autonomous_executions": sar.get("safe_autonomous"),
        "fallout": sar.get("fallout"),
        # Attempted without a human, whether or not it then succeeded. Reported
        # separately and named honestly: it is NOT the safe-autonomy rate.
        "unattended_executions": unattended,
        "unattended_rate_pct": round(unattended / total * 100, 1) if total else None,
        "success_rate_pct": round(succeeded / total * 100, 1) if total else None,
        "machine_time_hours": round(machine_seconds / 3600, 3),
        "total_cost_usd": round(total_cost, 4),
        "cost_per_successful_execution_usd": (
            round(total_cost / succeeded, 6) if succeeded and total_cost else None
        ),
        "total_hours_saved": None,
        "total_cost_reduction": None,
        # Honest ROI: a real number ONLY for skills with a configured baseline,
        # null otherwise. The frontend tile reads value_delivered_usd.
        "value_delivered_usd": value_delivered,
        "value_delivered_note": value_note,
        "priced_skills": skills_priced,
        "note": (
            "hours_saved and cost_reduction require a human-baseline duration and loaded "
            "hourly rate per skill, which are tenant inputs. They are null rather than estimated. "
            "safe_autonomy_rate_pct counts only executions that ran without a human AND "
            "completed cleanly; unattended_rate_pct is the looser 'no human involved' measure."
        ),
        "currency": "USD",
    }


async def _value_delivered(db: AsyncSession, tenant_id: str):
    """(value_usd, note, priced_skill_count).

    value is the sum over cleanly-succeeded executions of skills that HAVE a
    baseline, of (baseline_minutes / 60 * loaded_hourly_rate). If no skill has a
    baseline the value is None with an explanatory note — never fabricated.
    """
    from app.models.billing import SkillValueBaseline
    baselines = (await db.execute(
        select(SkillValueBaseline).where(SkillValueBaseline.tenant_id == tenant_id)
    )).scalars().all()
    if not baselines:
        return None, (
            "No per-skill baseline configured, so value delivered cannot be measured. "
            "Configure baseline_minutes and a loaded hourly rate per skill to see it."
        ), 0

    by_skill = {b.skill_id_name: b for b in baselines}
    counts = (await db.execute(
        select(SkillExecution.skill_id_name, func.count(SkillExecution.id))
        .where(
            SkillExecution.tenant_id == tenant_id,
            func.upper(SkillExecution.status).like("SUCCESS%"),
            SkillExecution.skill_id_name.in_(list(by_skill.keys())),
        )
        .group_by(SkillExecution.skill_id_name)
    )).all()

    total = Decimal("0")
    for skill_name, n in counts:
        b = by_skill[skill_name]
        per_run = (Decimal(b.baseline_minutes) / Decimal(60)) * Decimal(b.loaded_hourly_rate_usd)
        total += per_run * Decimal(int(n))
    return round(float(total), 2), (
        f"Measured from {len(baselines)} configured skill baseline(s); "
        f"skills without a baseline contribute nothing."
    ), len(baselines)


@router.get("/entitlements")
async def get_entitlements(
    tenant: dict = Depends(get_tenant),
    db: AsyncSession = Depends(get_db),
):
    """This tenant's plan, included features, and current-period metered usage
    against the plan allowance."""
    from app.core.entitlements import (
        entitlements_for_plan, plan_for_tenant, FEATURES, _managed_cloud,
    )
    from app.services.usage_rating import rate_tenant_period
    tenant_id = tenant["tenant_id"]
    plan = await plan_for_tenant(db, tenant_id)
    granted = entitlements_for_plan(plan)
    rating = await rate_tenant_period(db, tenant_id)
    return {
        "tenant_id": tenant_id,
        "plan": plan,
        "managed_cloud": _managed_cloud(),
        # Self-host: every feature is available regardless of plan.
        "features": {f: (f in granted or not _managed_cloud()) for f in sorted(FEATURES)},
        "usage": rating,
    }


@router.post("/webhook")
async def stripe_webhook(request: Request):
    """Inbound Stripe webhook. PUBLIC path (no tenant session — see the
    /billing/webhook carve-out in TenantMiddleware); authenticity is the Stripe
    signature over the raw body, never a tenant id from the payload."""
    from app.core.database import MaintenanceSessionLocal
    from app.services.stripe_bridge import get_billing_provider, handle_webhook_event
    provider = get_billing_provider()
    if not provider.enabled:
        raise HTTPException(status_code=404, detail="Billing is not enabled on this install")
    payload = await request.body()
    sig = request.headers.get("Stripe-Signature", "")
    try:
        event = provider.verify_webhook(payload, sig)
    except Exception:
        # Do not leak whether it was a bad signature vs malformed body.
        raise HTTPException(status_code=400, detail="Invalid webhook signature")
    # The webhook has no tenant context; billing_accounts is under RLS, so the
    # tenant is resolved from OUR records by stripe_customer_id on the RLS-exempt
    # owner session (an app-role session would set no app.tenant_id GUC and match
    # zero rows - the tenant is never taken from the Stripe payload).
    async with MaintenanceSessionLocal() as owner:
        return await handle_webhook_event(owner, event)
