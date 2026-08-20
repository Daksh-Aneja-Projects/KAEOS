"""S5.6.7 — the lifespan bootstrap must be SERIALIZED across workers.

`init_db()` + the RLS sweep + every seed run on all 8 gunicorn workers and on
every replica. Each step is idempotent-by-CHECK but not atomic, so two workers
can both pass "is it seeded?" before either writes. `hold()` serializes them:
the winner bootstraps, each next worker then re-runs the same steps and their
already-seeded checks no-op.

Serializing, NOT skipping, is the point - a worker that skipped would begin
serving traffic against a schema the winner has not finished creating. These
tests pin that shape, plus the two ways it could quietly break: the guard not
releasing on an exception, and the Postgres backend leaking its held connection.
"""
import asyncio

import pytest

from app.services.leader_lock import LeaderLock, hold


class StubLock:
    """Grants only after `deny` refusals. `hold()` uses acquire/release only."""

    def __init__(self, deny: int = 0):
        self.deny = deny
        self.acquires = 0
        self.releases = 0

    async def acquire(self) -> bool:
        self.acquires += 1
        return self.acquires > self.deny

    async def release(self) -> None:
        self.releases += 1


@pytest.fixture
def sleeps(monkeypatch):
    """Count (and skip) the retry backoff so the test is instant."""
    recorded: list[float] = []

    async def _fake_sleep(delay):
        recorded.append(delay)

    monkeypatch.setattr(asyncio, "sleep", _fake_sleep)
    return recorded


@pytest.mark.asyncio
async def test_waits_for_the_lock_then_runs_the_body(sleeps):
    """A worker refused the lock RETRIES until it wins - it never skips the
    bootstrap and boots against a half-built database."""
    lock = StubLock(deny=2)
    ran = []

    async with hold(lock):
        ran.append("bootstrap")

    assert ran == ["bootstrap"], "the body must run on every worker, not just the winner"
    assert lock.acquires == 3, "must retry until granted"
    assert len(sleeps) == 2, "one backoff per refusal"
    assert all(1.0 <= d < 2.0 for d in sleeps), "backoff must be jittered, not lockstep"
    assert lock.releases == 1, "the lock must be handed on, not held past bootstrap"


@pytest.mark.asyncio
async def test_release_runs_when_bootstrap_raises(sleeps):
    """A failed migration/seed must not wedge every other worker behind a lock
    that is only freed by its TTL."""
    lock = StubLock()

    with pytest.raises(RuntimeError, match="migration blew up"):
        async with hold(lock):
            raise RuntimeError("migration blew up")

    assert lock.releases == 1, "release must run on the exception path too"


@pytest.mark.asyncio
async def test_local_backend_never_waits(sleeps):
    """SQLite / single-instance dev: acquire() always grants, so the real lock
    adds zero latency and zero behaviour change on the dev path."""
    lock = LeaderLock("kaeos:test:bootstrap:local", ttl_seconds=300)

    async with hold(lock):
        pass

    assert lock.backend == "local"
    assert sleeps == [], "dev must not pay a retry backoff"


class StubConn:
    """A held Postgres connection whose unlock statement fails."""

    def __init__(self):
        self.closed = False

    async def execute(self, *_args, **_kwargs):
        raise OSError("connection reset")

    async def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_postgres_release_closes_the_connection_even_if_unlock_fails():
    """The advisory lock is held by a dedicated connection. If `release()` drops
    the reference without closing, every boot leaks one pool connection - which
    the short-lived bootstrap lock does on every process, every restart."""
    lock = LeaderLock("kaeos:test:bootstrap:pg", ttl_seconds=300)
    conn = StubConn()
    lock._backend = "postgres"
    lock._pg_conn = conn
    lock._is_leader = True

    await lock.release()   # swallows the unlock error by design

    assert conn.closed is True, "connection must be closed, not merely dereferenced"
    assert lock._pg_conn is None
    assert lock.is_leader is False
