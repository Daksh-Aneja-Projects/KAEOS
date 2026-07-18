import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select, and_
from datetime import datetime, timezone
from app.core.database import MaintenanceSessionLocal
from app.models.domain import Rule

logger = logging.getLogger(__name__)

_BATCH_LIMIT = 500


async def run_decay_checks():
    """Background task to check rule freshness and trigger decay.

    Uses the maintenance (owner) session so it bypasses RLS — this is a
    cross-tenant housekeeping job that must see all tenants' rules.
    Only processes rules that are active, validated, and have a half-life.
    """
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


def init_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        run_decay_checks, 'interval', minutes=60,
        id='decay_checks_job', replace_existing=True
    )
    return scheduler
