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

The inverse also holds: a row the pipeline NEVER evaluated is not a governed
run and must not be billed. The count therefore filters on GOVERNED_VOCABULARY
— the historical predictive-ops "ghost" rows (status ``QUEUED``, a value no
gate writes, drained by nothing) were being metered and pushed to the billing
provider as if they were work.
"""
import logging
from datetime import date, datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.entitlements import allowance_for_plan, plan_for_tenant
from app.models.billing import UsageMeterReport
from app.models.domain import SkillExecution
from app.models.execution_status import GOVERNED_VOCABULARY

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
    start = datetime(period.year, period.month, period.day, tzinfo=timezone.utc)
    end = datetime(nxt.year, nxt.month, nxt.day, tzinfo=timezone.utc)
    executions = await db.scalar(
        select(func.count(SkillExecution.id)).where(
            SkillExecution.tenant_id == tenant_id,
            SkillExecution.started_at >= start,
            SkillExecution.started_at < end,
            # Only rows the gate pipeline actually evaluated are billable.
            SkillExecution.status.in_(GOVERNED_VOCABULARY),
        )
    ) or 0
    metered = int(executions)
    by_class = None
    # Enterprise seam: outcome-verified billing. When a classifier is
    # registered, the metered unit becomes the VERIFIED OUTCOME (autonomous /
    # assisted; blocked is not billed), read from the gate trail and the
    # human-approval record - never from anything the acting agent can set.
    # It can only narrow the count; an erroring classifier leaves the plain
    # governed-run count in force (billing never fails open to zero or to
    # more than the runs that happened).
    from app.core.extensions import extensions
    if extensions.billing_classifier is not None:
        try:
            verdict = await extensions.billing_classifier(db, tenant_id, start, end)
        except Exception as e:
            logger.error("[Usage] outcome classifier failed; metering governed runs: %s", e)
            verdict = None
        if isinstance(verdict, dict) and isinstance(verdict.get("metered_executions"), int):
            metered = max(0, min(metered, int(verdict["metered_executions"])))
            by_class = verdict.get("by_class")
    plan = await plan_for_tenant(db, tenant_id)
    allowance = allowance_for_plan(plan)
    overage = max(0, metered - allowance)
    out = {
        "tenant_id": tenant_id,
        "period_start": period.isoformat(),
        "plan": plan,
        "governed_executions": int(executions),
        "metered_executions": metered,
        "included_allowance": allowance,
        "overage_units": overage,
    }
    if by_class is not None:
        out["metered_by_outcome"] = by_class
    return out


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
