"""KAEOS — Background-job leader election (multi-replica safety).

The singleton background loops (PreCog ambient loop, event-bus worker, the decay
scheduler, the retention sweep) must run on EXACTLY ONE process. Two replicas
running them means N× LLM spend and read-then-write races on the same rows.

Previously the only guard was the manual ``RUN_BACKGROUND_JOBS`` flag: an
operator had to remember to set it false on every replica but one. This module
makes leadership automatic, with three backends chosen by what infrastructure is
actually present:

  * **Redis** (preferred): ``SET key <id> NX PX ttl`` acquires; a Lua CAS renews
    and releases only if we still own the key. A crashed leader's key simply
    expires and a follower takes over within one TTL.
  * **Postgres advisory lock** (fallback when Redis is absent but the DB is
    Postgres): a dedicated connection holds ``pg_try_advisory_lock``; if the
    process dies the connection drops and the lock is released by the server.
  * **Local** (SQLite / no Redis — i.e. single-instance dev): always leader. No
    coordination is needed or possible, and dev/demo must keep working unchanged.

``run_election`` drives transitions and fires ``on_acquire`` / ``on_release`` so
callers can start/stop their loops exactly on leadership edges.
"""
from __future__ import annotations

import asyncio
import logging
import os
import socket
import uuid

logger = logging.getLogger(__name__)

# Atomic "renew only if I still hold it": avoids a process that lost leadership
# (its key already expired and was taken by another) from extending someone
# else's lease.
_RENEW_LUA = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('pexpire', KEYS[1], ARGV[2])
else
  return 0
end
"""
_RELEASE_LUA = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('del', KEYS[1])
else
  return 0
end
"""


def _advisory_keys(name: str) -> tuple[int, int]:
    """Two signed 32-bit ints for pg_try_advisory_lock(key1, key2) from a name."""
    import hashlib
    h = hashlib.sha256(name.encode()).digest()
    k1 = int.from_bytes(h[0:4], "big", signed=True)
    k2 = int.from_bytes(h[4:8], "big", signed=True)
    return k1, k2


class LeaderLock:
    def __init__(self, name: str = "kaeos:leader:background_jobs", ttl_seconds: int = 30):
        self.name = name
        self.ttl = ttl_seconds
        self.instance_id = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"
        self._is_leader = False
        self._backend: str | None = None       # "redis" | "postgres" | "local"
        self._pg_conn = None                    # held connection for advisory lock

    @property
    def is_leader(self) -> bool:
        return self._is_leader

    @property
    def backend(self) -> str | None:
        return self._backend

    async def _select_backend(self) -> str:
        if self._backend:
            return self._backend
        try:
            from app.core.redis import get_redis
            if await get_redis() is not None:
                self._backend = "redis"
                return self._backend
        except Exception:
            pass
        try:
            from app.core.database import engine
            if engine.dialect.name == "postgresql":
                self._backend = "postgres"
                return self._backend
        except Exception:
            pass
        self._backend = "local"
        return self._backend

    async def acquire(self) -> bool:
        """Attempt to become (or confirm we are) the leader. Returns is_leader."""
        backend = await self._select_backend()
        if backend == "redis":
            return await self._acquire_redis()
        if backend == "postgres":
            return await self._acquire_postgres()
        self._is_leader = True   # local: single instance always leads
        return True

    async def renew(self) -> bool:
        """Extend the lease if we still hold it. Returns whether we remain leader."""
        if not self._is_leader:
            return False
        backend = self._backend
        if backend == "redis":
            try:
                from app.core.redis import get_redis
                client = await get_redis()
                if client is None:
                    self._is_leader = False
                    return False
                ok = await client.eval(
                    _RENEW_LUA, 1, self.name, self.instance_id, str(self.ttl * 1000)
                )
                self._is_leader = bool(ok)
            except Exception as e:
                logger.warning("[Leader] renew failed: %s", e)
                self._is_leader = False
            return self._is_leader
        if backend == "postgres":
            # Advisory lock is held by the live connection; nothing to renew, but
            # confirm the connection is still alive — if it dropped we are no
            # longer the leader and must re-acquire.
            if self._pg_conn is None or self._pg_conn.closed:
                self._is_leader = False
            return self._is_leader
        return True  # local

    async def release(self) -> None:
        """Give up leadership (best-effort) so a follower can take over promptly."""
        backend = self._backend
        try:
            if backend == "redis" and self._is_leader:
                from app.core.redis import get_redis
                client = await get_redis()
                if client is not None:
                    await client.eval(_RELEASE_LUA, 1, self.name, self.instance_id)
            elif backend == "postgres" and self._pg_conn is not None:
                from sqlalchemy import text
                k1, k2 = _advisory_keys(self.name)
                try:
                    await self._pg_conn.execute(text("SELECT pg_advisory_unlock(:k1, :k2)"),
                                                {"k1": k1, "k2": k2})
                    await self._pg_conn.close()
                finally:
                    self._pg_conn = None
        except Exception as e:
            logger.warning("[Leader] release failed (lease will expire): %s", e)
        finally:
            self._is_leader = False

    async def _acquire_redis(self) -> bool:
        from app.core.redis import get_redis
        client = await get_redis()
        if client is None:                 # Redis vanished — degrade to no-leader
            self._is_leader = False
            return False
        try:
            got = await client.set(self.name, self.instance_id, nx=True, px=self.ttl * 1000)
            if got:
                self._is_leader = True
            elif self._is_leader:
                # We already own it — refresh under our own id.
                self._is_leader = await self.renew()
            else:
                self._is_leader = False
        except Exception as e:
            logger.warning("[Leader] redis acquire failed: %s", e)
            self._is_leader = False
        return self._is_leader

    async def _acquire_postgres(self) -> bool:
        if self._is_leader and self._pg_conn is not None and not self._pg_conn.closed:
            return True
        from sqlalchemy import text
        from app.core.database import engine
        k1, k2 = _advisory_keys(self.name)
        try:
            conn = await engine.connect()
            row = (await conn.execute(
                text("SELECT pg_try_advisory_lock(:k1, :k2)"), {"k1": k1, "k2": k2}
            )).scalar_one()
            if row:
                self._pg_conn = conn        # hold the connection == hold the lock
                self._is_leader = True
            else:
                await conn.close()
                self._is_leader = False
        except Exception as e:
            logger.warning("[Leader] postgres advisory acquire failed: %s", e)
            self._is_leader = False
        return self._is_leader


# Process-wide singleton used by main.py's lifespan.
leader_lock = LeaderLock()


async def run_election(lock: LeaderLock, on_acquire, on_release, interval: float | None = None):
    """Drive leadership: acquire when a follower, renew when leader, fire callbacks
    on the transition edges. Cancels cleanly, releasing the lock on the way out.

    ``interval`` defaults to a third of the TTL so a lease is renewed twice before
    it can expire. Callbacks may be sync or async; exceptions are logged, never
    propagated (a failing callback must not stop the election loop)."""
    interval = interval or max(2.0, lock.ttl / 3.0)

    async def _fire(cb):
        if cb is None:
            return
        try:
            res = cb()
            if asyncio.iscoroutine(res):
                await res
        except Exception as e:
            logger.error("[Leader] callback %s failed: %s", getattr(cb, "__name__", cb), e)

    try:
        while True:
            was_leader = lock.is_leader
            if was_leader:
                still = await lock.renew()
                if not still:
                    logger.warning("[Leader] lost leadership — stopping background loops")
                    await _fire(on_release)
            else:
                got = await lock.acquire()
                if got:
                    logger.info("[Leader] acquired leadership (%s, backend=%s) — starting loops",
                                lock.instance_id, lock.backend)
                    await _fire(on_acquire)
            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        if lock.is_leader:
            await _fire(on_release)
        await lock.release()
        raise
