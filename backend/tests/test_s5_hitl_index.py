"""S5.6 - the pending-approval queue must not scan the whole Redis keyspace.

``list_pending`` used to run ``KEYS kaeos:hitl:*`` (O(total keys), and KEYS
blocks the Redis event loop) plus one GET per match - on a poll the frontend
fires every 30s from every open tab, on every worker. It now reads a per-tenant
index SET and MGETs those records in one round trip.

The fake below deliberately implements NO ``keys()`` method, so any regression
back to the scanning implementation fails these tests instead of quietly
costing production latency.
"""
import json

import pytest

from app.services import hitl_manager as hm
from app.services.hitl_manager import HITLManager


class FakeRedis:
    """Enough async Redis for the HITL index: strings, sets, and SCAN.

    No ``keys()`` - that absence is the regression guard.
    """

    def __init__(self):
        self.store: dict[str, str] = {}
        self.sets: dict[str, set[str]] = {}
        self.expires: dict[str, int] = {}
        self.mget_calls = 0
        self.scan_calls = 0
        self.scan_counts: list[int | None] = []

    async def setex(self, key, ttl, value):
        self.store[key] = value
        self.expires[key] = ttl
        return True

    async def get(self, key):
        return self.store.get(key)

    async def mget(self, keys):
        self.mget_calls += 1
        return [self.store.get(k) for k in keys]

    async def sadd(self, key, *members):
        self.sets.setdefault(key, set()).update(members)
        return len(members)

    async def srem(self, key, *members):
        s = self.sets.get(key)
        if not s:
            return 0
        removed = len(s & set(members))
        s.difference_update(members)
        if not s:
            self.sets.pop(key, None)
        return removed

    async def smembers(self, key):
        return set(self.sets.get(key, ()))

    async def expire(self, key, ttl):
        self.expires[key] = ttl
        return 1

    async def exists(self, key):
        return int(key in self.store or key in self.sets)

    async def scan(self, cursor=0, match=None, count=None):
        """Cursor SCAN. Chunk is 1 regardless of ``count`` so the cursor loop
        in the code under test is genuinely exercised, not short-circuited."""
        self.scan_calls += 1
        self.scan_counts.append(count)
        assert match and match.endswith("*"), "SCAN must be prefix-bounded"
        prefix = match[:-1]
        keys = sorted(k for k in self.store if k.startswith(prefix))
        cursor = int(cursor)
        chunk = keys[cursor:cursor + 1]
        nxt = cursor + 1 if cursor + 1 < len(keys) else 0
        return nxt, chunk


@pytest.fixture
def mgr(monkeypatch):
    """A fresh manager (so the once-per-process backfill flag is fresh) wired
    to a fake Redis."""
    m = HITLManager()
    fake = FakeRedis()

    async def _get_redis():
        return fake

    monkeypatch.setattr(m, "_get_redis", _get_redis)
    m.fake = fake
    return m


@pytest.fixture(autouse=True)
def _mute_side_effects(monkeypatch):
    """The activity feed and the approver notification are not under test."""
    from app.services import notifier
    from app.services.activity_feed import ActivityFeedService

    async def _noop(self, **kwargs):
        return None

    monkeypatch.setattr(ActivityFeedService, "emit", _noop)
    monkeypatch.setattr(notifier, "notify_fire_and_forget", lambda *a, **k: None)


def _skill(skill_id="s5_index_skill"):
    return {"skill_id": skill_id, "department": "support",
            "steps": [{"step": 1, "name": "Assess", "prompt": "Assess."}],
            "compliance_tags": []}


def _record(exec_id, tenant_id, status="PENDING"):
    return json.dumps({"exec_id": exec_id, "tenant_id": tenant_id,
                       "status": status, "skill_id": "planted",
                       "skill_def": {"department": "support"}, "context": {}})


async def test_request_indexes_and_list_reads_it_with_one_mget(mgr):
    exec_id = "exec-s5-idx-1"
    await mgr.request_human_confirmation(
        _skill(), {"execution_id": exec_id, "tenant_id": "tenant_a"})

    assert await mgr.fake.smembers(mgr._index_key("tenant_a")) == {exec_id}
    assert mgr.fake.expires[mgr._index_key("tenant_a")] == hm._HITL_TTL
    # Record storage is unchanged, so old workers mid rolling deploy still read it.
    assert json.loads(mgr.fake.store[f"kaeos:hitl:{exec_id}"])["status"] == "PENDING"

    mgr.fake.mget_calls = 0
    pending = await mgr.list_pending("tenant_a")

    assert [p["exec_id"] for p in pending] == [exec_id]
    assert mgr.fake.mget_calls == 1, "records must be fetched in ONE round trip"
    assert mgr.fake.scan_calls == 0, "a populated index needs no scan"
    assert not hasattr(mgr.fake, "keys"), "KEYS must never be called"


async def test_resolve_removes_the_id_from_the_index(mgr):
    exec_id = "exec-s5-idx-2"
    await mgr.request_human_confirmation(
        _skill(), {"execution_id": exec_id, "tenant_id": "tenant_a"})

    # Rejection is terminal: no resume task to drain.
    assert await mgr.resolve_hitl(exec_id, approved=False, approver="tester") is True

    assert await mgr.fake.smembers(mgr._index_key("tenant_a")) == set()
    assert await mgr.list_pending("tenant_a") == []
    # The resolved record itself is still readable for the 5-minute reader window.
    assert (await mgr.get_hitl_status(exec_id))["status"] == "RESOLVED"


async def test_index_self_heals_when_the_record_is_gone(mgr):
    """A TTL-expired record leaves an orphan id in the index; the next read
    must skip it AND drop it, so the index converges instead of growing."""
    idx = mgr._index_key("tenant_a")
    await mgr.fake.sadd(idx, "ghost-id")
    mgr.fake.store["kaeos:hitl:live-id"] = _record("live-id", "tenant_a")
    await mgr.fake.sadd(idx, "live-id")

    pending = await mgr.list_pending("tenant_a")

    assert [p["exec_id"] for p in pending] == ["live-id"]
    assert await mgr.fake.smembers(idx) == {"live-id"}, "orphan not evicted"


async def test_backfill_rebuilds_indexes_from_existing_records(mgr):
    """Records written before this change (a rolling deploy) have no index.
    One SCAN pass rebuilds every tenant's index, then never runs again."""
    mgr.fake.store["kaeos:hitl:old-a"] = _record("old-a", "tenant_a")
    mgr.fake.store["kaeos:hitl:old-b"] = _record("old-b", "tenant_b")
    mgr.fake.store["kaeos:hitl:done-a"] = _record("done-a", "tenant_a", "RESOLVED")

    pending = await mgr.list_pending("tenant_a")

    assert [p["exec_id"] for p in pending] == ["old-a"], "wrong tenant's records leaked"
    assert mgr.fake.scan_calls >= 1, "backfill must scan"
    assert all(c == 200 for c in mgr.fake.scan_counts), "SCAN must stay bounded"
    assert await mgr.fake.smembers(mgr._index_key("tenant_b")) == {"old-b"}
    assert await mgr.fake.smembers(mgr._index_key("tenant_a")) == {"old-a"}, \
        "a resolved record must not be indexed as pending"

    scans = mgr.fake.scan_calls
    assert [p["exec_id"] for p in await mgr.list_pending("tenant_b")] == ["old-b"]
    assert mgr.fake.scan_calls == scans, "backfill must run at most once per process"


async def test_memory_fallback_still_works_without_redis(monkeypatch):
    """Redis absent (dev, or an outage): the in-memory store is unchanged."""
    m = HITLManager()

    async def _no_redis():
        return None

    monkeypatch.setattr(m, "_get_redis", _no_redis)
    exec_id = "exec-s5-idx-mem"
    await m.request_human_confirmation(
        _skill(), {"execution_id": exec_id, "tenant_id": "tenant_a"})

    assert [p["exec_id"] for p in await m.list_pending("tenant_a")] == [exec_id]
    assert await m.list_pending("tenant_b") == []

    assert await m.resolve_hitl(exec_id, approved=False, approver="tester") is True
    assert await m.list_pending("tenant_a") == []
