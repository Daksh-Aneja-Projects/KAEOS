"""Resolve the per-domain autonomy threshold (the Autonomy Dial) for Gate 3.

Executives set a per-domain ``min_confidence`` via /config/autonomy; Gate 3 in the
agent runtime consults it so the dial has real teeth. A short in-process cache
keeps this off the hot path for repeated executions; the PUT endpoint invalidates
the cache so a change takes effect promptly.
"""
from __future__ import annotations

import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)

_TTL_SECONDS = 30.0
_cache: dict[tuple[str, str], tuple[float, float]] = {}  # (tenant, domain) -> (value, expires_at)


def invalidate(tenant_id: str, domain: Optional[str] = None) -> None:
    if domain is None:
        for k in [k for k in _cache if k[0] == tenant_id]:
            _cache.pop(k, None)
    else:
        _cache.pop((tenant_id, str(domain).lower()), None)


async def resolve_min_confidence(tenant_id: str, domain: Optional[str]) -> float:
    """Return the confidence threshold a domain's actions must clear to run
    autonomously. No policy row means the platform default.

    FAILS CLOSED on a lookup error: an executive may have dialled this domain
    STRICTER than the platform default, so silently reverting to the default
    would loosen the gate exactly when the datastore is unhealthy. On error we
    keep the strictest threshold we have evidence for - the last value read for
    this key, even if its TTL has lapsed - and only fall back to the default
    when nothing has ever been read.
    """
    from app.core.config import get_settings
    default = get_settings().CONFIDENCE_AUTONOMOUS_EXEC
    if not domain:
        return default
    d = str(domain).lower()
    key = (tenant_id, d)
    now = time.monotonic()
    cached = _cache.get(key)
    if cached and cached[1] > now:
        return cached[0]
    val = default
    try:
        from sqlalchemy import select
        from app.core.database import AsyncSessionLocal
        from app.models.settings import AutonomyPolicy
        async with AsyncSessionLocal() as db:
            row = (await db.execute(
                select(AutonomyPolicy).where(
                    AutonomyPolicy.tenant_id == tenant_id, AutonomyPolicy.domain == d)
            )).scalar_one_or_none()
        if row is not None and row.min_confidence is not None:
            val = float(row.min_confidence)
    except Exception as e:
        stale = cached[0] if cached else default
        val = max(default, stale)
        logger.error(
            "[autonomy-dial] threshold lookup failed for %s/%s; holding the "
            "strictest known threshold %.3f (fail-closed): %s",
            tenant_id, d, val, e,
        )
        # Do NOT refresh the cache from a failed read - retry on the next call.
        return val
    _cache[key] = (val, now + _TTL_SECONDS)
    return val
