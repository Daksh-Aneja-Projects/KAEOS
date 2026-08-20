"""S5.6.3 / S5.6.4 - a Redis outage must not be permanent.

A worker that boots while Redis is down used to stay Redis-less for its whole
life (shared JWT revocation, rate limiting, WS fan-out all silently per-process),
and one slow ping at startup demoted the CacheBus to memory until restart. Both
now re-probe on a bounded cadence. These tests use a fake ``from_url`` and a fake
clock, so they never touch a real Redis.
"""
import asyncio

import redis.asyncio as redis_asyncio

from app.core import redis as redis_mod
from app.core.polystore import cache_bus as bus_mod
from app.core.polystore.cache_bus import MemoryCacheBus, RedisCacheBus


class _Clock:
    """Controllable stand-in for time.monotonic."""

    def __init__(self, t: float = 1000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


class _FakeRedis:
    def __init__(self, factory):
        self._factory = factory
        self.closed = False

    async def ping(self):
        if not self._factory.up:
            raise ConnectionError("connection refused")
        return True

    async def close(self):
        self.closed = True


class _Factory:
    """Counting stand-in for redis.asyncio.from_url."""

    def __init__(self, up: bool = False):
        self.up = up
        self.calls = 0
        self.clients: list[_FakeRedis] = []

    def __call__(self, *args, **kwargs) -> _FakeRedis:
        self.calls += 1
        client = _FakeRedis(self)
        self.clients.append(client)
        return client


def _install(monkeypatch, up=False):
    """Patch the shared redis.asyncio.from_url plus both module clocks."""
    factory = _Factory(up=up)
    clock = _Clock()
    monkeypatch.setattr(redis_asyncio, "from_url", factory)
    monkeypatch.setattr(redis_mod, "_now", clock)
    monkeypatch.setattr(bus_mod, "_now", clock)
    # Restored by monkeypatch even though the module writes them via ``global``.
    monkeypatch.setattr(redis_mod, "redis_client", None)
    monkeypatch.setattr(redis_mod, "_last_attempt", None)
    monkeypatch.setattr(bus_mod, "_cache_bus", None)
    monkeypatch.setattr(bus_mod, "_last_redis_probe", float("-inf"))
    return factory, clock


# --------------------------------------------------------------------------
# 6.3 - app.core.redis
# --------------------------------------------------------------------------

async def test_get_redis_reconnects_on_a_bounded_cadence(monkeypatch):
    """Booting during an outage must not cost the worker Redis forever, and
    must not re-ping a down Redis on every single request either."""
    factory, clock = _install(monkeypatch, up=False)

    # The replica starts while Redis is down.
    await redis_mod.init_redis()
    assert redis_mod.redis_client is None
    assert factory.calls == 1

    # Inside the window: no client, and crucially no extra connection attempts.
    assert await redis_mod.get_redis() is None
    clock.advance(redis_mod.RECONNECT_INTERVAL_SECONDS - 1)
    assert await redis_mod.get_redis() is None
    assert factory.calls == 1, "hammered a down Redis inside the retry window"

    # Window elapsed, Redis still down: exactly one more attempt.
    clock.advance(1)
    assert await redis_mod.get_redis() is None
    assert factory.calls == 2
    assert factory.clients[-1].closed, "failed probe leaked a connection pool"

    # Redis comes back, but the fresh window has to pass first.
    factory.up = True
    assert await redis_mod.get_redis() is None
    assert factory.calls == 2

    clock.advance(redis_mod.RECONNECT_INTERVAL_SECONDS)
    client = await redis_mod.get_redis()
    assert client is not None
    assert factory.calls == 3

    # Once connected it is latched again: no probing on the happy path.
    clock.advance(3600)
    assert await redis_mod.get_redis() is client
    assert factory.calls == 3


async def test_get_redis_never_probes_before_init(monkeypatch):
    """No init_redis() means this is not a served app (unit tests, CLI scripts).
    A getter must not open sockets on its own; REDIS_URL defaults to localhost,
    so probing here would silently pick up a developer's local Redis."""
    factory, clock = _install(monkeypatch, up=True)

    assert await redis_mod.get_redis() is None
    clock.advance(3600)
    assert await redis_mod.get_redis() is None
    assert factory.calls == 0


async def test_close_redis_ends_the_probing_window(monkeypatch):
    """Shutdown closes the client and stops the getter re-opening one; a clean
    restart re-probes immediately via init_redis(), with no window to wait out."""
    factory, clock = _install(monkeypatch, up=True)

    await redis_mod.init_redis()
    connected = redis_mod.redis_client
    assert connected is not None

    await redis_mod.close_redis()
    assert connected.closed
    assert redis_mod.redis_client is None
    assert await redis_mod.get_redis() is None
    assert factory.calls == 1, "getter re-opened Redis after shutdown"

    # Restart: immediate, not one interval later.
    await redis_mod.init_redis()
    assert redis_mod.redis_client is not None
    assert factory.calls == 2


# --------------------------------------------------------------------------
# 6.4 - app.core.polystore.cache_bus
# --------------------------------------------------------------------------

async def test_cache_bus_upgrades_from_memory_when_redis_returns(monkeypatch):
    """A cold-start blip must not pin the process to MemoryCacheBus for life."""
    factory, clock = _install(monkeypatch, up=False)

    bus = await bus_mod.get_cache_bus()
    assert isinstance(bus, MemoryCacheBus)
    assert factory.calls == 1

    # Latched: repeat calls inside the window re-probe nothing.
    assert await bus_mod.get_cache_bus() is bus
    clock.advance(bus_mod.REDIS_REPROBE_SECONDS - 1)
    assert await bus_mod.get_cache_bus() is bus
    assert factory.calls == 1, "re-probed Redis inside the window"

    # Window elapsed, still down: one attempt, still memory.
    clock.advance(1)
    assert isinstance(await bus_mod.get_cache_bus(), MemoryCacheBus)
    assert factory.calls == 2
    assert factory.clients[-1].closed, "failed probe leaked a connection pool"

    # Redis is back: next window upgrades the bus in place.
    factory.up = True
    clock.advance(bus_mod.REDIS_REPROBE_SECONDS)
    upgraded = await bus_mod.get_cache_bus()
    assert isinstance(upgraded, RedisCacheBus)
    assert factory.calls == 3

    # Redis is latched: no further probing.
    clock.advance(3600)
    assert await bus_mod.get_cache_bus() is upgraded
    assert factory.calls == 3


async def test_cache_bus_will_not_strand_a_live_subscriber(monkeypatch):
    """Swapping the bus object would leave a subscriber holding a queue on a
    memory bus nobody publishes to, so a live subscriber blocks the upgrade."""
    factory, clock = _install(monkeypatch, up=False)

    bus = await bus_mod.get_cache_bus()
    assert isinstance(bus, MemoryCacheBus)

    agen = bus.subscribe("chan")
    task = asyncio.create_task(anext(agen))
    await asyncio.sleep(0)  # let the generator register its queue and block
    assert any(bus._subscribers.values())

    factory.up = True
    clock.advance(bus_mod.REDIS_REPROBE_SECONDS)
    assert await bus_mod.get_cache_bus() is bus
    assert factory.calls == 1, "upgraded out from under a live subscriber"

    # Subscriber leaves -> the upgrade is free again.
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert not any(bus._subscribers.values())

    clock.advance(bus_mod.REDIS_REPROBE_SECONDS)
    assert isinstance(await bus_mod.get_cache_bus(), RedisCacheBus)
