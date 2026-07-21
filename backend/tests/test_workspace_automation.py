"""
Sprints 6-10 backend tests: assignment/My-Work/workload, comments+mentions,
automation rules (validation + firing), notifications/digest, saved segments,
and CSV export.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient

TENANT = "tenant_acme"


async def _new_ticket(db, status="NEW", aged_hours=0):
    from app.support.models.tickets import Ticket, TicketStatus
    t = Ticket(tenant_id=TENANT, ticket_number=f"T-{uuid.uuid4().hex[:10]}",
               subject="workspace probe", description="d", status=TicketStatus(status))
    db.add(t)
    await db.commit()
    await db.refresh(t)
    if aged_hours:
        from sqlalchemy import update
        from app.support.models.tickets import Ticket as T
        stamp = datetime.now(timezone.utc) - timedelta(hours=aged_hours)
        await db.execute(update(T).where(T.id == t.id).values(updated_at=stamp, created_at=stamp))
        await db.commit()
    return t


# ── Assignment (Sprint 6) ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_assign_shows_in_my_work_and_workload(async_client: AsyncClient, db):
    t = await _new_ticket(db)
    r = await async_client.post(f"/api/v1/org/entities/ticket/{t.id}/assign",
                                json={"assignee": "dev_user", "note": "please handle"})
    assert r.status_code == 200, r.text
    assert r.json()["assignee"] == "dev_user"

    # Dev tenant identity is "dev_user" (no email) -> my-work returns it.
    r = await async_client.get("/api/v1/org/my-work")
    body = r.json()
    assert body["assignee"] == "dev_user"
    item = next(i for i in body["items"] if i["entity_id"] == t.id)
    assert item["state"] == "NEW"
    assert item["title"] == "workspace probe"

    r = await async_client.get("/api/v1/org/workload")
    assert any(w["assignee"] == "dev_user" and w["count"] >= 1 for w in r.json()["workload"])


@pytest.mark.asyncio
async def test_assign_is_upsert_and_unassign(async_client: AsyncClient, db):
    t = await _new_ticket(db)
    await async_client.post(f"/api/v1/org/entities/ticket/{t.id}/assign", json={"assignee": "a@x"})
    await async_client.post(f"/api/v1/org/entities/ticket/{t.id}/assign", json={"assignee": "b@x"})
    r = await async_client.get(f"/api/v1/org/entities/ticket/{t.id}/assignment")
    assert r.json()["assignee"] == "b@x"  # upserted, not duplicated

    r = await async_client.delete(f"/api/v1/org/entities/ticket/{t.id}/assign")
    assert r.status_code == 200
    r = await async_client.get(f"/api/v1/org/entities/ticket/{t.id}/assignment")
    assert r.json()["assignee"] is None


@pytest.mark.asyncio
async def test_assign_unknown_entity_404(async_client: AsyncClient):
    r = await async_client.post("/api/v1/org/entities/ticket/does-not-exist/assign",
                                json={"assignee": "x"})
    assert r.status_code == 404


# ── Comments (Sprint 7) ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_comment_thread_and_mentions(async_client: AsyncClient, db):
    t = await _new_ticket(db)
    r = await async_client.post(f"/api/v1/org/entities/ticket/{t.id}/comments",
                                json={"body": "Looping in @alice@corp.com and @bob to review."})
    assert r.status_code == 201, r.text
    assert set(r.json()["mentions"]) == {"alice@corp.com", "bob"}

    await async_client.post(f"/api/v1/org/entities/ticket/{t.id}/comments",
                            json={"body": "second note"})
    r = await async_client.get(f"/api/v1/org/entities/ticket/{t.id}/comments")
    thread = r.json()
    assert len(thread) == 2
    assert thread[0]["body"].startswith("Looping")  # chronological

    # A mention raised an activity-feed notification.
    from sqlalchemy import select
    from app.models.agent_factory import ActivityFeedEvent
    q = await db.execute(select(ActivityFeedEvent).where(
        ActivityFeedEvent.tenant_id == TENANT,
        ActivityFeedEvent.source_id == t.id))
    assert any("mentioned" in e.title for e in q.scalars().all())


@pytest.mark.asyncio
async def test_comment_delete_by_author(async_client: AsyncClient, db):
    t = await _new_ticket(db)
    r = await async_client.post(f"/api/v1/org/entities/ticket/{t.id}/comments",
                                json={"body": "delete me"})
    cid = r.json()["id"]
    r = await async_client.delete(f"/api/v1/org/comments/{cid}")
    assert r.status_code == 200
    r = await async_client.get(f"/api/v1/org/entities/ticket/{t.id}/comments")
    assert r.json() == []


# ── Automation (Sprint 8) ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_rule_validation_rejects_illegal_transition(async_client: AsyncClient):
    # NEW -> RESOLVED is not a legal ticket transition.
    r = await async_client.post("/api/v1/org/rules", json={
        "name": "bad", "entity_type": "ticket", "trigger_state": "NEW",
        "dwell_hours": 1, "action_type": "transition", "action_to_state": "RESOLVED",
    })
    assert r.status_code == 422
    assert "cannot go" in r.json()["detail"]

    r = await async_client.post("/api/v1/org/rules", json={
        "name": "bad2", "entity_type": "unicorn", "trigger_state": "NEW",
        "dwell_hours": 1, "action_type": "escalate",
    })
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_rule_transition_fires_on_dwell(async_client: AsyncClient, db):
    # Auto-assign-ish: NEW tickets older than 4h auto-advance to OPEN.
    r = await async_client.post("/api/v1/org/rules", json={
        "name": "auto-open stale new tickets", "entity_type": "ticket",
        "trigger_state": "NEW", "dwell_hours": 4,
        "action_type": "transition", "action_to_state": "OPEN",
    })
    assert r.status_code == 201, r.text

    stale = await _new_ticket(db, status="NEW", aged_hours=10)   # matches
    fresh = await _new_ticket(db, status="NEW", aged_hours=1)    # too new
    stale_id, fresh_id = stale.id, fresh.id   # capture before expiring the session

    r = await async_client.post("/api/v1/org/rules/run")
    body = r.json()
    assert body["actions_fired"] == 1

    from app.support.models.tickets import Ticket
    from sqlalchemy import select
    db.expire_all()  # drop this session's identity-map cache; read fresh from DB
    q = await db.execute(select(Ticket).where(Ticket.id == stale_id))
    assert q.scalar_one().status.value == "OPEN"
    q = await db.execute(select(Ticket).where(Ticket.id == fresh_id))
    assert q.scalar_one().status.value == "NEW"

    # times_fired incremented on the rule.
    r = await async_client.get("/api/v1/org/rules")
    assert any(rule["times_fired"] == 1 for rule in r.json())


@pytest.mark.asyncio
async def test_rule_assign_action(async_client: AsyncClient, db):
    r = await async_client.post("/api/v1/org/rules", json={
        "name": "assign stale to triage bot", "entity_type": "ticket",
        "trigger_state": "NEW", "dwell_hours": 2,
        "action_type": "assign", "action_assignee": "triage-bot",
    })
    assert r.status_code == 201, r.text
    t = await _new_ticket(db, status="NEW", aged_hours=5)
    await async_client.post("/api/v1/org/rules/run")

    r = await async_client.get(f"/api/v1/org/entities/ticket/{t.id}/assignment")
    assert r.json()["assignee"] == "triage-bot"


@pytest.mark.asyncio
async def test_rule_toggle_and_delete(async_client: AsyncClient, db):
    r = await async_client.post("/api/v1/org/rules", json={
        "name": "temp", "entity_type": "ticket", "trigger_state": "NEW",
        "dwell_hours": 1, "action_type": "escalate",
    })
    rid = r.json()["id"]
    r = await async_client.patch(f"/api/v1/org/rules/{rid}?is_active=false")
    assert r.json()["is_active"] is False

    # Inactive rule fires nothing.
    await _new_ticket(db, status="NEW", aged_hours=5)
    r = await async_client.post("/api/v1/org/rules/run")
    assert r.json()["actions_fired"] == 0

    r = await async_client.delete(f"/api/v1/org/rules/{rid}")
    assert r.status_code == 200


# ── Notifications + digest (Sprint 9) ────────────────────────────────────

@pytest.mark.asyncio
async def test_notifications_and_digest(async_client: AsyncClient, db):
    # Generate a mention notification.
    t = await _new_ticket(db)
    await async_client.post(f"/api/v1/org/entities/ticket/{t.id}/comments",
                            json={"body": "ping @dev_user"})
    r = await async_client.get("/api/v1/org/notifications")
    body = r.json()
    assert "counts" in body and isinstance(body["items"], list)

    r = await async_client.get("/api/v1/org/digest")
    d = r.json()
    assert set(d) >= {"org_health", "domains", "notifications", "workload", "action_required"}
    assert len(d["domains"]) == 7


# ── Segments + export (Sprint 10) ────────────────────────────────────────

@pytest.mark.asyncio
async def test_saved_segments_crud(async_client: AsyncClient):
    r = await async_client.post("/api/v1/org/segments", json={
        "domain": "support", "name": "Urgent open", "entity_type": "ticket",
        "definition": {"status": "OPEN", "priority": "URGENT"},
    })
    assert r.status_code == 201, r.text
    sid = r.json()["id"]

    r = await async_client.get("/api/v1/org/segments?domain=support")
    assert any(s["id"] == sid and s["name"] == "Urgent open" for s in r.json())

    r = await async_client.delete(f"/api/v1/org/segments/{sid}")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_segment_rejects_unknown_entity(async_client: AsyncClient):
    r = await async_client.post("/api/v1/org/segments", json={
        "domain": "support", "name": "bad", "entity_type": "unicorn", "definition": {},
    })
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_csv_export(async_client: AsyncClient, db):
    await _new_ticket(db)
    r = await async_client.get("/api/v1/org/export/ticket.csv")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    text = r.text
    header = text.splitlines()[0]
    assert "ticket_number" in header and "status" in header
    assert "tenant_id" not in header      # tenant column withheld from export
    assert len(text.splitlines()) >= 2    # header + at least one row


@pytest.mark.asyncio
async def test_csv_export_unknown_404(async_client: AsyncClient):
    r = await async_client.get("/api/v1/org/export/unicorn.csv")
    assert r.status_code == 404
