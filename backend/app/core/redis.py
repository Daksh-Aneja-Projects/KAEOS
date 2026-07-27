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
        logger.warning(f"[Redis] Unreachable ({e}) - falling back to in-memory queues")


async def get_redis():
    """Return the shared Redis client, or None when Redis is not available."""
    return redis_client


async def close_redis():
    global redis_client
    if redis_client:
        await redis_client.close()
        redis_client = None
