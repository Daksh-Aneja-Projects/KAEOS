"""Content-addressed cache for expensive derived results.

The endpoints this exists for spend tens of seconds in a local model to turn a
handful of numbers into a report. Re-running that for inputs that have not
changed is pure waste: the same three counts produce the same analysis.

The cache key is a fingerprint of the INPUTS, not just a name plus a clock. That
is the whole point, and it is what makes this safe rather than a staleness
tradeoff: if the underlying data changes, the fingerprint changes, so the old
entry can never be served for new inputs. It becomes unreachable, not wrong. A
TTL is still applied as a backstop, so entries expire if the model, the prompt
or anything else outside the fingerprint changes.

Rules for using this:
  - Fingerprint EVERY input the result depends on. A missed input is the one way
    to get a stale answer.
  - Never fingerprint a timestamp that moves on its own, or nothing ever hits.
  - Only cache successful results. Caching a fallback would pin the failure.
"""
import hashlib
import json
import logging
from typing import Any, Awaitable, Callable, Optional, Sequence

from app.core.polystore import get_cache_bus

logger = logging.getLogger(__name__)

# Long enough that a working session is a single computation, short enough that
# an entry whose inputs are not fully fingerprinted cannot live all day.
DEFAULT_TTL_SECONDS = 3600


def fingerprint(parts: Sequence[Any]) -> str:
    """A stable short hash of the inputs a result depends on."""
    raw = json.dumps(parts, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def make_key(namespace: str, tenant_id: str, parts: Sequence[Any]) -> str:
    return f"resultcache:{namespace}:{tenant_id}:{fingerprint(parts)}"


async def get_or_compute(
    namespace: str,
    tenant_id: str,
    parts: Sequence[Any],
    producer: Callable[[], Awaitable[Any]],
    ttl: int = DEFAULT_TTL_SECONDS,
    should_cache: Optional[Callable[[Any], bool]] = None,
) -> tuple[Any, bool]:
    """Return ``(value, was_cached)`` for this namespace and input fingerprint.

    ``producer`` is only awaited on a miss. ``should_cache`` decides whether a
    freshly produced value is worth storing, so a degraded or fallback result is
    recomputed next time instead of being pinned for the whole TTL.

    A cache backend failure is never fatal: it degrades to computing the value,
    which is exactly the behaviour before this cache existed.
    """
    key = make_key(namespace, tenant_id, parts)
    bus = None
    try:
        bus = await get_cache_bus()
        hit = await bus.get(key)
        if hit is not None:
            return json.loads(hit), True
    except Exception:
        logger.warning("[ResultCache] read failed for %s, computing", namespace, exc_info=True)

    value = await producer()

    if bus is not None and (should_cache is None or should_cache(value)):
        try:
            await bus.set(key, json.dumps(value, default=str), ttl=ttl)
        except Exception:
            logger.warning("[ResultCache] write failed for %s", namespace, exc_info=True)
    return value, False


async def peek(namespace: str, tenant_id: str, parts: Sequence[Any]) -> Optional[Any]:
    """Return a cached value for these inputs, or None. Never computes.

    For callers that cannot express their work as a single ``producer``, such as
    a streaming endpoint that has to emit deltas while it builds the result.
    """
    try:
        bus = await get_cache_bus()
        hit = await bus.get(make_key(namespace, tenant_id, parts))
        return json.loads(hit) if hit is not None else None
    except Exception:
        logger.warning("[ResultCache] peek failed for %s", namespace, exc_info=True)
        return None


async def put(
    namespace: str, tenant_id: str, parts: Sequence[Any], value: Any,
    ttl: int = DEFAULT_TTL_SECONDS,
) -> None:
    """Store a value under these inputs. Pairs with ``peek``. Never raises."""
    try:
        bus = await get_cache_bus()
        await bus.set(make_key(namespace, tenant_id, parts), json.dumps(value, default=str), ttl=ttl)
    except Exception:
        logger.warning("[ResultCache] put failed for %s", namespace, exc_info=True)


async def _demo() -> None:
    """Self-check: a hit skips the producer, and changed inputs never hit."""
    calls = {"n": 0}

    async def produce():
        calls["n"] += 1
        return {"report": f"generated {calls['n']}"}

    v1, cached1 = await get_or_compute("demo", "t1", [1, 2, 3], produce)
    v2, cached2 = await get_or_compute("demo", "t1", [1, 2, 3], produce)
    assert calls["n"] == 1, "second call must not run the producer"
    assert cached2 is True and cached1 is False
    assert v1 == v2

    # A changed input must NOT return the old value.
    v3, cached3 = await get_or_compute("demo", "t1", [1, 2, 4], produce)
    assert cached3 is False and v3 != v1, "changed inputs must miss"

    # A different tenant must not read another tenant's entry.
    v4, cached4 = await get_or_compute("demo", "t2", [1, 2, 3], produce)
    assert cached4 is False, "tenants must not share entries"

    # should_cache=False means never stored, so it recomputes every time.
    before = calls["n"]
    for _ in range(2):
        await get_or_compute("demo", "t1", [9], produce, should_cache=lambda v: False)
    assert calls["n"] == before + 2, "unstorable results must recompute"

    # peek/put share the fingerprint with get_or_compute, so a value stored by
    # the streaming path is found by the non-streaming one and vice versa.
    assert await peek("demo", "t1", [7, 7]) is None
    await put("demo", "t1", [7, 7], {"v": 1})
    assert await peek("demo", "t1", [7, 7]) == {"v": 1}
    assert await peek("demo", "t1", [7, 8]) is None, "changed inputs must not hit"
    assert await peek("demo", "t2", [7, 7]) is None, "tenants must not share"
    hit, was_cached = await get_or_compute("demo", "t1", [7, 7], produce)
    assert was_cached and hit == {"v": 1}, "put must be visible to get_or_compute"
    print("result_cache._demo OK")


if __name__ == "__main__":
    import asyncio
    asyncio.run(_demo())
