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


async def run_foundry_mining():
    """Continuously curate governed executions into training examples (AI Foundry).

    Makes "continuously improve" real: instead of an operator manually POSTing
    /foundry/datasets/build, the dataset grows on a cadence from every tenant's
    governed executions. Leader-guarded and idempotent (already-mined executions
    carry source='mined' and are skipped), so a double-run is safe. Promotion of
    any resulting model stays HUMAN-gated - this only fills the funnel.
    """
    if not _is_leader():
        return
    logger.info("[Scheduler] Running AI Foundry dataset mining...")
    try:
        from app.services.foundry import dataset_builder
        from app.models.domain import SkillExecution
        async with MaintenanceSessionLocal() as db:
            tenant_ids = (await db.execute(
                select(SkillExecution.tenant_id).distinct()
            )).scalars().all()
            total, tenants = 0, 0
            for tid in tenant_ids:
                if not tid:
                    continue
                tenants += 1
                result = await dataset_builder.mine_executions(db, tid)
                total += int(result.get("created", 0) or 0)
            logger.info(
                "[Scheduler] Foundry mining curated %d new example(s) across %d tenant(s)",
                total, tenants,
            )
    except Exception as e:
        logger.error(f"[Scheduler] Foundry mining failed: {e}")


async def run_deployment_reaper():
    """Recover deployments orphaned by a crashed/restarted worker.

    The deployment pipeline is a fire-and-forget task; if its worker dies the row
    hangs in a non-terminal state. This leader-guarded sweep transitions stuck
    deployments to FAILED so they surface instead of hanging forever.
    """
    if not _is_leader():
        return
    try:
        from app.workforce.deployment.studio import DeploymentStudio
        async with MaintenanceSessionLocal() as db:
            recovered = await DeploymentStudio.recover_orphaned_deployments(db)
        if recovered:
            logger.info("[Scheduler] Deployment reaper recovered %d orphaned deployment(s)", len(recovered))
    except Exception as e:
        logger.error(f"[Scheduler] Deployment reaper failed: {e}")


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
    # AI Foundry: mine governed executions into training examples on a cadence so
    # the improvement loop is continuous, not manual. Promotion stays human-gated.
    scheduler.add_job(
        run_foundry_mining, 'interval', hours=6,
        id='foundry_mining_job', replace_existing=True
    )
    # Recover deployments orphaned by a worker crash/restart (fire-and-forget
    # pipeline has no durable queue yet); frequent + cheap.
    scheduler.add_job(
        run_deployment_reaper, 'interval', minutes=15,
        id='deployment_reaper_job', replace_existing=True
    )
    return scheduler
