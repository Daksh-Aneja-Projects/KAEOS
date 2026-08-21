"""KAEOS Polystore — Cache + pub/sub bus abstraction.

Standardizes the Redis-or-degrade pattern that previously lived scattered across
``core/redis.py``, ``services/event_bus.py`` and ``services/hitl_manager.py``.

Two backends:

  * ``RedisCacheBus``  — wraps an ``redis.asyncio`` client (get/set/setex/delete +
                         publish/subscribe). Used when Redis is reachable.
  * ``MemoryCacheBus`` — in-process dict with TTL expiry and asyncio-queue pub/sub.
                         Used when Redis is unavailable (single-instance dev stack).

Use :func:`get_cache_bus` to obtain the active bus (async, cached).
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from abc import ABC, abstractmethod
from typing import Any, AsyncIterator, Optional

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class CacheBus(ABC):
    """Abstract cache + pub/sub bus."""

    backend_name: str = "abstract"

    @abstractmethod
    async def get(self, key: str) -> Optional[str]: ...

    @abstractmethod
    async def set(self, key: str, value: str, ttl: Optional[int] = None) -> None: ...

    @abstractmethod
    async def delete(self, key: str) -> None: ...

    @abstractmethod
    async def publish(self, channel: str, message: str) -> None: ...

    @abstractmethod
    def subscribe(self, channel: str) -> AsyncIterator[str]:
        """Async iterator yielding messages published to ``channel``."""

    @abstractmethod
    async def health(self) -> dict[str, Any]: ...


class RedisCacheBus(CacheBus):
    """Redis-backed cache + pub/sub."""

    backend_name = "redis"

    def __init__(self, client):
        self._client = client

    async def get(self, key):
        return await self._client.get(key)

    async def set(self, key, value, ttl=None):
        if ttl:
            await self._client.setex(key, ttl, value)
        else:
            await self._client.set(key, value)

    async def delete(self, key):
        await self._client.delete(key)

    async def publish(self, channel, message):
        await self._client.publish(channel, message)

    async def subscribe(self, channel) -> AsyncIterator[str]:
        pubsub = self._client.pubsub()
        await pubsub.subscribe(channel)
        try:
            async for message in pubsub.listen():
                if message.get("type") == "message":
                    yield message["data"]
        finally:
            await pubsub.unsubscribe(channel)

    async def health(self):
        try:
            await self._client.ping()
            return {"backend": self.backend_name, "available": True}
        except Exception as e:
            return {"backend": self.backend_name, "available": False, "error": str(e)}


class MemoryCacheBus(CacheBus):
    """In-process cache + pub/sub for single-instance / no-Redis operation."""

    backend_name = "memory"

    # Expiry was lazy-only (checked on get), so keys written and never re-read —
    # e.g. fingerprint-keyed result_cache misses — were immortal. Sweep on a
    # cadence of writes, with a hard cap as the backstop.
    _SWEEP_EVERY = 256
    _MAX_ENTRIES = 10_000

    def __init__(self):
        self._store: dict[str, tuple[Optional[float], str]] = {}  # key -> (expires_at, value)
        self._subscribers: dict[str, list[asyncio.Queue]] = {}
        self._sets = 0

    def _expired(self, key: str) -> bool:
        entry = self._store.get(key)
        if not entry:
            return True
        expires_at, _ = entry
        if expires_at is not None and time.time() > expires_at:
            self._store.pop(key, None)
            return True
        return False

    async def get(self, key):
        if self._expired(key):
            return None
        return self._store[key][1]

    async def set(self, key, value, ttl=None):
        expires_at = (time.time() + ttl) if ttl else None
        self._store[key] = (expires_at, value)
        self._sets += 1
        if self._sets % self._SWEEP_EVERY == 0 or len(self._store) > self._MAX_ENTRIES:
            now = time.time()
            for k in [k for k, (exp, _) in self._store.items()
                      if exp is not None and now > exp]:
                self._store.pop(k, None)
            # ponytail: FIFO overflow eviction (dicts keep insertion order);
            # upgrade to LRU if a no-Redis install ever churns past the cap.
            while len(self._store) > self._MAX_ENTRIES:
                self._store.pop(next(iter(self._store)))

    async def delete(self, key):
        self._store.pop(key, None)

    async def publish(self, channel, message):
        for q in list(self._subscribers.get(channel, [])):
            try:
                q.put_nowait(message)
            except asyncio.QueueFull:
                # A slow subscriber must not block the publisher or other
                # subscribers; dropping is the documented pub/sub semantic here
                # (this is the in-memory dev fallback, not the Redis path).
                pass

    async def subscribe(self, channel) -> AsyncIterator[str]:
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._subscribers.setdefault(channel, []).append(q)
        try:
            while True:
                yield await q.get()
        finally:
            subs = self._subscribers.get(channel, [])
            if q in subs:
                subs.remove(q)

    async def health(self):
        return {"backend": self.backend_name, "available": True, "keys": len(self._store)}


_cache_bus: Optional[CacheBus] = None

# A cold-start Redis blip used to demote the process to MemoryCacheBus until
# restart. While the memory fallback is active, re-probe Redis this often.
REDIS_REPROBE_SECONDS = 30

_now = time.monotonic  # seam for tests; production never rebinds it
_last_redis_probe: float = float("-inf")


async def _connect_redis_bus() -> Optional[RedisCacheBus]:
    """One bounded Redis probe. Returns a RedisCacheBus, or None if unreachable."""
    global _last_redis_probe
    # Written before the first await, so a concurrent caller sees a fresh
    # timestamp and skips: that is the stampede guard, no flag needed.
    _last_redis_probe = _now()
    client = None
    try:
        import redis.asyncio as redis
        client = redis.from_url(get_settings().REDIS_URL, decode_responses=True)
        await asyncio.wait_for(client.ping(), timeout=1.0)
        return RedisCacheBus(client)
    except Exception as e:
        if client is not None:
            with contextlib.suppress(Exception):
                await client.close()  # else every probe leaks a connection pool
        logger.info("[Polystore] Redis unavailable (%s), CacheBus backend = memory", e)
        return None


async def get_cache_bus() -> CacheBus:
    """Return the active CacheBus. Prefers Redis when reachable, else in-memory.

    While the memory fallback is active this re-probes Redis every
    ``REDIS_REPROBE_SECONDS`` and upgrades in place, so a blip at startup does not
    cost the process its shared cache for the rest of its life.
    """
    global _cache_bus, _last_redis_probe
    if _cache_bus is None:
        _cache_bus = await _connect_redis_bus() or MemoryCacheBus()
        if isinstance(_cache_bus, RedisCacheBus):
            logger.info("[Polystore] CacheBus backend = redis")
        return _cache_bus

    if (isinstance(_cache_bus, MemoryCacheBus)
            and _now() - _last_redis_probe >= REDIS_REPROBE_SECONDS):
        # Cached entries are best-effort and fine to drop on upgrade, but a
        # subscriber holds a queue on THIS object: swapping the bus out would
        # strand it on a memory bus nobody publishes to. Nothing calls
        # CacheBus.subscribe() today (result_cache.py is get/set/delete only, and
        # ws.py / event_bus.py subscribe on raw clients from core.redis), so the
        # upgrade is normally free; this keeps it honest if that ever changes.
        if any(_cache_bus._subscribers.values()):
            _last_redis_probe = _now()
            logger.info("[Polystore] Staying on memory CacheBus: live subscribers "
                        "cannot be re-pointed at Redis")
        elif (upgraded := await _connect_redis_bus()) is not None:
            _cache_bus = upgraded
            logger.info("[Polystore] CacheBus upgraded to redis")
    return _cache_bus


def reset_cache_bus() -> None:
    """Testing helper — clear the cached bus so it is re-selected on next call."""
    global _cache_bus, _last_redis_probe
    _cache_bus = None
    _last_redis_probe = float("-inf")
