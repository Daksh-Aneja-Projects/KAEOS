"""Resolve the per-domain autonomy threshold (the Autonomy Dial) for Gate 3.

Executives set a per-domain ``min_confidence`` via /config/autonomy; Gate 3 in the
agent runtime consults it so the dial has real teeth. A short in-process cache
keeps this off the hot path for repeated executions; the PUT endpoint invalidates
the cache so a change takes effect promptly.
"""
from __future__ import annotations

import time
from typing import Optional

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
    autonomously. Falls back to the platform default when no policy exists or on
    any error (fail-safe toward the configured default, never toward 0)."""
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
    except Exception:
        val = default
    _cache[key] = (val, now + _TTL_SECONDS)
    return val
