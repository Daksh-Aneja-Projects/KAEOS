import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select, and_
from datetime import datetime, timezone
from app.core.database import MaintenanceSessionLocal
from app.models.domain import Rule

logger = logging.getLogger(__name__)

_BATCH_LIMIT = 500


def _is_leader() -> bool:
    """Belt-and-suspenders: only the elected leader runs scheduled jobs.

    The leader is normally the only replica that even starts the scheduler, but
    this guard closes the brief window after a lost lease and makes every job
    safe to schedule everywhere.
    """
    try:
        from app.services.leader_lock import leader_lock
        return leader_lock.is_leader
    except Exception:
        return True   # no leader machinery → single instance → proceed


async def run_decay_checks():
    """Background task to check rule freshness and trigger decay.

    Uses the maintenance (owner) session so it bypasses RLS — this is a
    cross-tenant housekeeping job that must see all tenants' rules.
    Only processes rules that are active, validated, and have a half-life.
    """
    if not _is_leader():
        return
    logger.info("[Scheduler] Running background decay check...")
    try:
        async with MaintenanceSessionLocal() as db:
            now = datetime.now(timezone.utc)
            res = await db.execute(
                select(Rule)
                .where(
                    and_(
                        Rule.is_archived == False,
                        Rule.validated_at.isnot(None),
                        Rule.half_life_days > 0,
                    )
                )
                .limit(_BATCH_LIMIT)
            )
            rules = res.scalars().all()

            decay_count = 0
            for rule in rules:
                days_since = (now - rule.validated_at.replace(tzinfo=timezone.utc)).days
                if days_since > rule.half_life_days:
                    decay_factor = days_since // rule.half_life_days
                    new_conf = max(0.1, rule.confidence_scalar * (0.9 ** decay_factor))

                    if new_conf < rule.confidence_scalar:
                        rule.confidence_scalar = new_conf
                        decay_count += 1

            if decay_count > 0:
                await db.commit()
                logger.info(f"[Scheduler] Decayed {decay_count} rules due to age.")
            else:
                logger.info("[Scheduler] No rules required decay.")
    except Exception as e:
        logger.error(f"[Scheduler] Decay check failed: {e}")


async def run_retention_sweep():
    """Enforce configured data-retention windows across every tenant.

    Opt-in per tenant/data-class (see app/services/retention.py). Leader-guarded
    and idempotent — deleting rows already gone is a no-op — so an accidental
    double-run wastes work but never corrupts. Runs on the owner session via
    ``sweep_all_tenants`` which iterates tenants under each one's RLS context.
    """
    if not _is_leader():
        return
    logger.info("[Scheduler] Running data-retention sweep...")
    try:
        from app.services import retention
        receipts = await retention.sweep_all_tenants(dry_run=False)
        purged = sum(r.get("total", 0) for r in receipts if isinstance(r, dict))
        logger.info("[Scheduler] Retention sweep purged %d rows across %d tenants",
                    purged, len(receipts))
    except Exception as e:
        logger.error(f"[Scheduler] Retention sweep failed: {e}")


def init_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        run_decay_checks, 'interval', minutes=60,
        id='decay_checks_job', replace_existing=True
    )
    # Retention enforcement runs daily — windows are day-granular, so an hourly
    # sweep would be pure churn. Only tenants that opted a data class in are touched.
    scheduler.add_job(
        run_retention_sweep, 'interval', hours=24,
        id='retention_sweep_job', replace_existing=True
    )
    return scheduler
