"""Shared Redis client lifecycle.

NOTE: the rate limiter lives in ``app/core/middleware.py`` (``RateLimitMiddleware``),
which is the one ``main.py`` registers. A second, unregistered class of the same
name used to live here and silently failed OPEN when Redis errored; it was dead
code shadowing the live implementation by name, so it was removed rather than
left as a landmine for a future import.
"""
import logging

import redis.asyncio as redis

from app.core.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()

redis_client = None


async def init_redis():
    """Connect to Redis if reachable; otherwise run without it (in-memory fallbacks)."""
    global redis_client
    try:
        client = redis.from_url(settings.REDIS_URL, decode_responses=True)
        await client.ping()
        redis_client = client
        logger.info(f"[Redis] Connected: {settings.REDIS_URL}")
    except Exception as e:
        redis_client = None
        # In a production-like deploy this is more than a queue fallback: the
        # rate-limit counter degrades to per-worker in-memory, so each uvicorn
        # worker enforces its own separate budget and the real ceiling multiplies
        # by the worker count. Surface it loudly so operators wire Redis.
        try:
            if settings.is_production_like:
                logger.error(
                    "[Redis] UNREACHABLE in production (%s). Rate limiting and other "
                    "shared counters are now PER-WORKER in-memory, not cluster-wide. "
                    "Configure a reachable REDIS_URL before serving traffic.", e)
            else:
                logger.warning(f"[Redis] Unreachable ({e}) - falling back to in-memory queues")
        except Exception:
            logger.warning(f"[Redis] Unreachable ({e}) - falling back to in-memory queues")


async def get_redis():
    """Return the shared Redis client, or None when Redis is not available."""
    return redis_client


async def close_redis():
    global redis_client
    if redis_client:
        await redis_client.close()
        redis_client = None
