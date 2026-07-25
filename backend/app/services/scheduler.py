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


async def run_job_queue():
    """Drain the durable job queue (leader-guarded).

    Replaces fire-and-forget ``asyncio.create_task`` for long-running work: jobs
    are persisted before execution, so nothing is lost on a worker crash. The
    processor itself is leader-guarded inside ``process_jobs``.
    """
    try:
        from app.services import job_queue
        result = await job_queue.process_jobs()
        if result.get("succeeded") or result.get("failed") or result.get("retried"):
            logger.info("[Scheduler] Job queue drained: %s", result)
    except Exception as e:
        logger.error(f"[Scheduler] Job queue processing failed: {e}")


async def run_job_queue_reaper():
    """Requeue durable jobs a crashed worker left RUNNING (at-least-once)."""
    try:
        from app.services import job_queue
        recovered = await job_queue.requeue_stuck_jobs()
        if recovered:
            logger.info("[Scheduler] Job queue reaper recovered %d job(s)", len(recovered))
    except Exception as e:
        logger.error(f"[Scheduler] Job queue reaper failed: {e}")


async def run_autonomy_governor_job():
    """L5-reverse: nudge each tenant's per-domain autonomy dial from the measured
    safe-autonomy-rate (bounded; respects human-set dials). Leader-guarded."""
    if not _is_leader():
        return
    try:
        from app.services.autonomy_governor import run_autonomy_governor
        from app.models.domain import SkillExecution
        async with MaintenanceSessionLocal() as db:
            tenant_ids = (await db.execute(
                select(SkillExecution.tenant_id).distinct()
            )).scalars().all()
            adjusted = 0
            for tid in tenant_ids:
                if not tid:
                    continue
                receipt = await run_autonomy_governor(db, tid)
                adjusted += receipt.get("adjusted", 0)
            if adjusted:
                logger.info("[Scheduler] Autonomy governor adjusted %d domain dial(s)", adjusted)
    except Exception as e:
        logger.error(f"[Scheduler] Autonomy governor failed: {e}")


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
    # Register durable-job handlers before the processor can tick.
    try:
        from app.services.job_handlers import register_all
        register_all()
    except Exception as e:
        logger.error(f"[Scheduler] Failed to register job handlers: {e}")

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        run_decay_checks, 'interval', minutes=60,
        id='decay_checks_job', replace_existing=True
    )
    # Durable job queue: drain due jobs frequently (deployments start within a
    # tick), and reap jobs a crashed worker left RUNNING.
    scheduler.add_job(
        run_job_queue, 'interval', seconds=15,
        id='job_queue_job', replace_existing=True, max_instances=1, coalesce=True,
    )
    scheduler.add_job(
        run_job_queue_reaper, 'interval', minutes=5,
        id='job_queue_reaper_job', replace_existing=True
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
    # L5-reverse autonomy governor: adapt per-domain dials from the measured
    # safe-autonomy-rate on a cadence (bounded nudges; human-set dials untouched).
    scheduler.add_job(
        run_autonomy_governor_job, 'interval', hours=6,
        id='autonomy_governor_job', replace_existing=True
    )
    # Recover deployments orphaned by a worker crash/restart (fire-and-forget
    # pipeline has no durable queue yet); frequent + cheap.
    scheduler.add_job(
        run_deployment_reaper, 'interval', minutes=15,
        id='deployment_reaper_job', replace_existing=True
    )
    return scheduler
