import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select
from datetime import datetime, timezone
from app.core.database import AsyncSessionLocal
from app.models.domain import Rule

logger = logging.getLogger(__name__)

async def run_decay_checks():
    """Background task to check rule freshness and trigger decay."""
    logger.info("[Scheduler] Running background decay check...")
    try:
        async with AsyncSessionLocal() as db:
            now = datetime.now(timezone.utc)
            # Find rules where (now - validated_at) > half_life_days
            # SQLite specific (julianday difference) or fallback logic.
            # For simplicity, we just fetch all and check in python, or use a naive SQL filter if supported.
            # In production with Postgres, we'd use: 
            #   now() - validated_at > interval '1 day' * half_life_days
            
            res = await db.execute(select(Rule).where(Rule.is_archived == False))
            rules = res.scalars().all()
            
            decay_count = 0
            for rule in rules:
                if not rule.validated_at or not rule.half_life_days:
                    continue
                    
                days_since = (now - rule.validated_at.replace(tzinfo=timezone.utc)).days
                if days_since > rule.half_life_days:
                    # Decay confidence by 10% each half life
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
    # Run every 60 minutes in production, but for demo we run it every 5 minutes
    scheduler.add_job(run_decay_checks, 'interval', minutes=5, id='decay_checks_job', replace_existing=True)
    return scheduler
