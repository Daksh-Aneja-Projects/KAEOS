"""
Usage rating: governed agent executions (gate-pipeline runs) are the metered
unit. A tenant's SkillExecution rows in a billing period are counted, the plan's
included allowance is subtracted, and the overage is what a metered subscription
bills for.

Every gate-pipeline run persists a SkillExecution row — including runs BLOCKED
early at Gate 1 (compliance), which previously returned without persisting and
so were never counted (see runtime._persist_blocked_execution). A governed run
that the platform evaluated is a governed run whether or not it was allowed to
act.
"""
import logging
from datetime import date, datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.entitlements import allowance_for_plan, plan_for_tenant
from app.models.billing import UsageMeterReport
from app.models.domain import SkillExecution

logger = logging.getLogger(__name__)


def period_start_of(when: datetime | None = None) -> date:
    """First day of the billing month containing `when` (UTC)."""
    d = (when or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return date(d.year, d.month, 1)


def _next_period_start(p: date) -> date:
    return date(p.year + 1, 1, 1) if p.month == 12 else date(p.year, p.month + 1, 1)


async def rate_tenant_period(
    db: AsyncSession, tenant_id: str, period: date | None = None
) -> dict:
    """Count governed executions in the period and derive the overage.

    Pure read — does not persist. `db` must already be tenant-scoped (RLS) or an
    owner session; the WHERE clause filters by tenant_id either way.
    """
    period = period or period_start_of()
    nxt = _next_period_start(period)
    executions = await db.scalar(
        select(func.count(SkillExecution.id)).where(
            SkillExecution.tenant_id == tenant_id,
            SkillExecution.started_at >= datetime(period.year, period.month, period.day, tzinfo=timezone.utc),
            SkillExecution.started_at < datetime(nxt.year, nxt.month, nxt.day, tzinfo=timezone.utc),
        )
    ) or 0
    plan = await plan_for_tenant(db, tenant_id)
    allowance = allowance_for_plan(plan)
    overage = max(0, executions - allowance)
    return {
        "tenant_id": tenant_id,
        "period_start": period.isoformat(),
        "plan": plan,
        "metered_executions": int(executions),
        "included_allowance": allowance,
        "overage_units": overage,
    }


async def record_and_report(
    db: AsyncSession, tenant_id: str, period: date | None = None
) -> dict:
    """Upsert the period's UsageMeterReport and push overage to the billing
    provider (no-op self-host). Idempotent: the report is keyed on
    (tenant, period) and the provider push uses action=set, so re-running a
    period reports the same total, never an increment."""
    rating = await rate_tenant_period(db, tenant_id, period)
    period = period or period_start_of()

    row = (await db.execute(
        select(UsageMeterReport).where(
            UsageMeterReport.tenant_id == tenant_id,
            UsageMeterReport.period_start == period,
        )
    )).scalar_one_or_none()
    if row is None:
        row = UsageMeterReport(tenant_id=tenant_id, period_start=period)
        db.add(row)
    row.metered_executions = rating["metered_executions"]
    row.included_allowance = rating["included_allowance"]
    row.overage_units = rating["overage_units"]

    from app.services.stripe_bridge import get_billing_provider
    provider = get_billing_provider()
    try:
        result = await provider.report_usage(db, tenant_id, period, rating["overage_units"])
        row.stripe_status = result.get("status", "noop")
        row.stripe_usage_record_id = result.get("usage_record_id")
        if result.get("status") == "reported":
            row.reported_at = datetime.now(timezone.utc)
    except Exception as e:
        # Never let a billing-provider outage abort metering; the report row is
        # persisted and the next tick re-reports the same total idempotently.
        logger.warning("[Usage] provider push failed for %s: %s", tenant_id, e)
        row.stripe_status = "error"

    await db.commit()
    rating["stripe_status"] = row.stripe_status
    return rating
