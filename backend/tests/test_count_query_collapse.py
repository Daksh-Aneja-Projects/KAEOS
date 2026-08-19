"""Guards the count/aggregate collapse on /system/stats and the activity feed.

/system/stats builds its 13 entity counts and 2 averages from ONE SELECT of
scalar subqueries. The key-order assertion below is the byte-identity guard:
the response JSON must not shift if the query shape is changed again.
"""
import pytest

from app.models.domain import Rule, Skill, Employee
from app.services.activity_feed import ActivityFeedService
from app.models.agent_factory import ActivityEventType


EXPECTED_KEYS = [
    "rules", "skills", "signals", "workflows", "employees", "questions",
    "connectors", "executions", "decay_events", "audit_logs",
    "redteam_scans", "conflicts", "provenance_entries",
]


@pytest.mark.asyncio
async def test_system_stats_shape_and_counts(async_client, db):
    t = "t_pkgc_stats"
    db.add(Rule(tenant_id=t, statement="s", trigger_json={}, action_json={},
                confidence_scalar=0.5, is_archived=False))
    db.add(Rule(tenant_id=t, statement="s2", trigger_json={}, action_json={},
                confidence_scalar=0.9, is_archived=True))
    db.add(Skill(tenant_id=t, skill_id="k", success_rate=0.25))
    db.add(Employee(tenant_id=t, display_name="e"))
    await db.commit()

    r = await async_client.get("/api/v1/system/stats", headers={"X-Tenant-ID": t})
    assert r.status_code == 200, r.text
    body = r.json()
    assert list(body["entity_counts"].keys()) == EXPECTED_KEYS
    assert body["entity_counts"]["rules"] == 2
    assert body["entity_counts"]["skills"] == 1
    assert body["entity_counts"]["employees"] == 1
    assert body["entity_counts"]["provenance_entries"] == 0
    # avg over non-archived rules only
    assert body["avg_confidence"] == 0.5
    assert body["avg_success_rate"] == 0.25
    assert set(body) == {"entity_counts", "avg_confidence", "avg_success_rate", "timestamp"}


@pytest.mark.asyncio
async def test_system_stats_empty_tenant_is_zeros(async_client):
    r = await async_client.get("/api/v1/system/stats", headers={"X-Tenant-ID": "t_pkgc_empty"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body["entity_counts"].values()) == {0}
    assert body["avg_confidence"] == 0
    assert body["avg_success_rate"] == 0


@pytest.mark.asyncio
async def test_unread_counts():
    """Writes through the service (its own AsyncSessionLocal, not the db fixture)."""
    svc = ActivityFeedService()
    t = "t_pkgc_feed"
    a = await svc.emit(ActivityEventType.AGENT_STARTED, "a", t, requires_action=True)
    b = await svc.emit(ActivityEventType.AGENT_STARTED, "b", t, requires_action=True)
    await svc.emit(ActivityEventType.AGENT_STARTED, "c", t)
    await svc.mark_read([b.id], t)
    await svc.mark_action_taken(b.id, t)
    assert await svc.get_unread_count(t) == {"unread": 2, "action_required": 1}
    assert len(await svc.get_action_required(t)) == 1
    assert a.id != b.id


@pytest.mark.asyncio
async def test_employee_questions_not_eager(db):
    """lazy="selectin" removed: attribute access must now be a lazy load."""
    from sqlalchemy import inspect as sa_inspect
    from sqlalchemy import select
    db.add(Employee(tenant_id="t_pkgc_emp", display_name="x"))
    await db.commit()
    db.expunge_all()
    emp = (await db.execute(select(Employee).where(
        Employee.tenant_id == "t_pkgc_emp"))).scalars().first()
    assert "questions" in sa_inspect(emp).unloaded
