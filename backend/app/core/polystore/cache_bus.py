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

    def __init__(self):
        self._store: dict[str, tuple[Optional[float], str]] = {}  # key -> (expires_at, value)
        self._subscribers: dict[str, list[asyncio.Queue]] = {}

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

    async def delete(self, key):
        self._store.pop(key, None)

    async def publish(self, channel, message):
        for q in list(self._subscribers.get(channel, [])):
            try:
                q.put_nowait(message)
            except asyncio.QueueFull:
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


async def get_cache_bus() -> CacheBus:
    """Return the active CacheBus. Prefers Redis when reachable, else in-memory."""
    global _cache_bus
    if _cache_bus is not None:
        return _cache_bus

    settings = get_settings()
    try:
        import redis.asyncio as redis
        client = redis.from_url(settings.REDIS_URL, decode_responses=True)
        await asyncio.wait_for(client.ping(), timeout=1.0)
        _cache_bus = RedisCacheBus(client)
        logger.info("[Polystore] CacheBus backend = redis")
    except Exception as e:
        logger.info(f"[Polystore] Redis unavailable ({e}) — CacheBus backend = memory")
        _cache_bus = MemoryCacheBus()
    return _cache_bus


def reset_cache_bus() -> None:
    """Testing helper — clear the cached bus so it is re-selected on next call."""
    global _cache_bus
    _cache_bus = None
