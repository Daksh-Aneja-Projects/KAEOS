"""S5.6.2 - recent gate timings are bounded PER TENANT, not globally.

The old store was one module-global deque(maxlen=50) shared by every tenant, so
a single busy tenant evicted every other tenant's entries and a quiet tenant's
own latency view went empty. It was never a cross-tenant data leak (the reader
always filtered by tenant_id); the defect is eviction fairness.
"""
import pytest

from app.agents import runtime
from app.api.routes.safe_autonomy import get_latency


@pytest.fixture(autouse=True)
def _clean_store():
    runtime.RECENT_STAGE_TIMINGS.clear()
    yield
    runtime.RECENT_STAGE_TIMINGS.clear()


def _entry(tenant: str, n: int) -> dict:
    return {
        "execution_id": f"{tenant}-{n}",
        "tenant_id": tenant,
        "skill_id": "refund",
        "status": "SUCCESS_CLEAN",
        "pipeline_ms": 100 + n,
        "stages": [{"gate": "compliance", "ms": 12}],
    }


def test_busy_tenant_does_not_evict_a_quiet_tenant():
    # Order is load-bearing: the quiet tenant records FIRST, then the noisy
    # neighbour floods. Under the old single deque(maxlen=50) the flood pushed
    # the quiet tenant's three entries out and its latency view went empty.
    for n in range(3):
        runtime.record_stage_timing(_entry("tenant_quiet", n))
    for n in range(60):
        runtime.record_stage_timing(_entry("tenant_busy", n))

    busy = runtime.recent_stage_timings("tenant_busy")
    quiet = runtime.recent_stage_timings("tenant_quiet")

    # Bounded per tenant, keeping the newest 50 of the 60.
    assert len(busy) == 50
    assert busy[0]["execution_id"] == "tenant_busy-10"
    assert busy[-1]["execution_id"] == "tenant_busy-59"
    # Fairness: this is the assertion the old global deque failed (it returned
    # []) - all three of the quiet tenant's entries survive the flood.
    assert [t["execution_id"] for t in quiet] == [
        "tenant_quiet-0", "tenant_quiet-1", "tenant_quiet-2",
    ]


def test_unknown_tenant_reads_empty():
    runtime.record_stage_timing(_entry("tenant_a", 0))
    assert runtime.recent_stage_timings("tenant_nobody") == []


def test_tenant_count_is_lru_capped():
    for i in range(201):
        runtime.record_stage_timing(_entry(f"tenant_{i}", 0))

    assert len(runtime.RECENT_STAGE_TIMINGS) == 200
    # The least recently written tenant is the one dropped.
    assert runtime.recent_stage_timings("tenant_0") == []
    assert len(runtime.recent_stage_timings("tenant_1")) == 1
    assert len(runtime.recent_stage_timings("tenant_200")) == 1


def test_appending_refreshes_lru_position():
    for i in range(200):
        runtime.record_stage_timing(_entry(f"tenant_{i}", 0))
    runtime.record_stage_timing(_entry("tenant_0", 1))  # touch the oldest
    runtime.record_stage_timing(_entry("tenant_new", 0))  # forces one eviction

    assert len(runtime.RECENT_STAGE_TIMINGS) == 200
    assert len(runtime.recent_stage_timings("tenant_0")) == 2
    assert runtime.recent_stage_timings("tenant_1") == []


async def test_latency_endpoint_serves_this_tenants_timings(db):
    for n in range(25):
        runtime.record_stage_timing(_entry("tenant_reader", n))
    runtime.record_stage_timing(_entry("tenant_other", 0))

    payload = await get_latency(hours=24, tenant_id="tenant_reader", db=db)

    recent = payload["recent_executions"]
    assert len(recent) == 20  # the route still serves the last 20
    assert {t["tenant_id"] for t in recent} == {"tenant_reader"}
    assert recent[-1]["execution_id"] == "tenant_reader-24"
    assert set(recent[0]) == {
        "execution_id", "tenant_id", "skill_id", "status", "pipeline_ms", "stages",
    }
