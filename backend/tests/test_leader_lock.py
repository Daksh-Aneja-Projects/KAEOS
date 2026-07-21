"""Background-job leader election.

Proves the three-backend LeaderLock behaves:
  * local (SQLite / no Redis): always leader — single-instance dev unchanged;
  * redis: mutual exclusion (only one holder) + atomic CAS renew/release so a
    process that lost the lease cannot extend or delete someone else's key;
  * the election loop fires on_acquire / on_release on the leadership edges.
"""
import time

import pytest

from app.services.leader_lock import LeaderLock, run_election


class FakeRedis:
    """Minimal async Redis supporting SET NX PX, GET, and the two CAS Lua evals."""
    def __init__(self):
        self.store: dict[str, tuple[str, float | None]] = {}

    def _live(self, key):
        cur = self.store.get(key)
        if not cur:
            return None
        val, exp = cur
        if exp is not None and exp < time.monotonic():
            self.store.pop(key, None)
            return None
        return val

    async def set(self, key, val, nx=False, px=None):
        if nx and self._live(key) is not None:
            return None
        exp = time.monotonic() + px / 1000 if px else None
        self.store[key] = (val, exp)
        return True

    async def get(self, key):
        return self._live(key)

    async def eval(self, script, numkeys, *args):
        key, ident = args[0], args[1]
        cur = self._live(key)
        if "pexpire" in script:                       # renew
            if cur == ident:
                self.store[key] = (ident, time.monotonic() + int(args[2]) / 1000)
                return 1
            return 0
        if "del" in script:                           # release
            if cur == ident:
                self.store.pop(key, None)
                return 1
            return 0
        return 0


@pytest.mark.asyncio
async def test_local_backend_is_always_leader():
    """No Redis + SQLite engine → local backend → always leader (dev path)."""
    lock = LeaderLock("kaeos:test:local", ttl_seconds=5)
    assert await lock.acquire() is True
    assert lock.is_leader is True
    assert lock.backend == "local"
    assert await lock.renew() is True


@pytest.mark.asyncio
async def test_redis_backend_is_mutually_exclusive(monkeypatch):
    fake = FakeRedis()

    async def _get_redis():
        return fake
    monkeypatch.setattr("app.core.redis.get_redis", _get_redis)

    a = LeaderLock("kaeos:test:excl", ttl_seconds=30)
    b = LeaderLock("kaeos:test:excl", ttl_seconds=30)

    assert await a.acquire() is True
    assert a.backend == "redis"
    assert await b.acquire() is False, "two replicas must not both be leader"

    await a.release()
    assert await b.acquire() is True, "follower takes over after leader releases"


@pytest.mark.asyncio
async def test_renew_fails_when_key_stolen(monkeypatch):
    """A process that lost its lease cannot renew (CAS by instance id)."""
    fake = FakeRedis()

    async def _get_redis():
        return fake
    monkeypatch.setattr("app.core.redis.get_redis", _get_redis)

    a = LeaderLock("kaeos:test:steal", ttl_seconds=30)
    assert await a.acquire() is True

    # Simulate another instance now owning the key.
    fake.store["kaeos:test:steal"] = ("someone-else", time.monotonic() + 30)

    assert await a.renew() is False
    assert a.is_leader is False


@pytest.mark.asyncio
async def test_release_only_deletes_own_key(monkeypatch):
    """Release must not delete a key another instance now holds."""
    fake = FakeRedis()

    async def _get_redis():
        return fake
    monkeypatch.setattr("app.core.redis.get_redis", _get_redis)

    a = LeaderLock("kaeos:test:rel", ttl_seconds=30)
    assert await a.acquire() is True
    fake.store["kaeos:test:rel"] = ("other", time.monotonic() + 30)

    await a.release()
    assert fake._live("kaeos:test:rel") == "other", "must not delete another's key"


@pytest.mark.asyncio
async def test_election_loop_fires_callbacks_on_edges():
    import asyncio

    events = []
    lock = LeaderLock("kaeos:test:election", ttl_seconds=5)

    def on_acquire():
        events.append("acquire")

    def on_release():
        events.append("release")

    task = asyncio.create_task(
        run_election(lock, on_acquire=on_acquire, on_release=on_release, interval=0.05)
    )
    await asyncio.sleep(0.15)          # let it acquire (local backend)
    assert "acquire" in events
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    assert events[-1] == "release", "cancellation must relinquish leadership"
