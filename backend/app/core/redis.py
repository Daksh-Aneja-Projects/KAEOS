"""Shared Redis client lifecycle.

NOTE: the rate limiter lives in ``app/core/middleware.py`` (``RateLimitMiddleware``),
which is the one ``main.py`` registers. A second, unregistered class of the same
name used to live here and silently failed OPEN when Redis errored; it was dead
code shadowing the live implementation by name, so it was removed rather than
left as a landmine for a future import.
"""
import asyncio
import contextlib
import logging
import time

import redis.asyncio as redis

from app.core.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()

redis_client = None

# A worker that booted during a Redis outage used to stay Redis-less for its whole
# life: JWT revocation, rate limiting and WS fan-out silently stayed per-process
# even after Redis came back. ``get_redis()`` therefore re-probes, but at most once
# per interval so a down Redis is not hammered once per request.
RECONNECT_INTERVAL_SECONDS = 15
PROBE_TIMEOUT_SECONDS = 1.0

_now = time.monotonic  # seam for tests; production never rebinds it

# Seconds (``_now()``) of the last connection attempt. ``None`` means ``init_redis()``
# has never run, i.e. this process is not a served app (unit tests, CLI scripts) and
# a getter must not open sockets on its behalf.
_last_attempt: float | None = None


async def init_redis():
    """Connect to Redis if reachable; otherwise run without it (in-memory fallbacks)."""
    global redis_client, _last_attempt
    _last_attempt = _now()
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
    """Return the shared Redis client, or None when Redis is not available.

    Re-probes a previously unreachable Redis at most once every
    ``RECONNECT_INTERVAL_SECONDS`` so the process rejoins cluster-wide state on its
    own. No stampede guard is needed: ``_last_attempt`` is written *before* the
    first await, and asyncio cannot preempt between the check and that write, so a
    concurrent caller already sees a fresh timestamp and skips.
    """
    global redis_client, _last_attempt
    if redis_client is not None or _last_attempt is None:
        return redis_client
    if _now() - _last_attempt < RECONNECT_INTERVAL_SECONDS:
        return None

    _last_attempt = _now()
    client = None
    try:
        client = redis.from_url(settings.REDIS_URL, decode_responses=True)
        # Bounded: this runs on the request path (rate-limit middleware), and a
        # blackholed host would otherwise stall it for the full TCP connect timeout.
        await asyncio.wait_for(client.ping(), timeout=PROBE_TIMEOUT_SECONDS)
        redis_client = client
        logger.info("[Redis] Reconnected: %s", settings.REDIS_URL)
    except Exception as e:
        if client is not None:
            with contextlib.suppress(Exception):
                await client.close()  # else every probe leaks a connection pool
        logger.debug("[Redis] Still unreachable (%s); retrying in %ss",
                     e, RECONNECT_INTERVAL_SECONDS)
    return redis_client


async def close_redis():
    global redis_client, _last_attempt
    if redis_client:
        await redis_client.close()
        redis_client = None
    # A clean shutdown ends the probing window too: the next init_redis() decides.
    _last_attempt = None
