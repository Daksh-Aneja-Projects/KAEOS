"""find_stale_entities pushes the SLA predicate into SQL. That rewrite has to
agree with the Python age loop on the cases real data rarely shows: a NULL
updated_at falling back to created_at, a naive timestamp, and a row whose
updated_at is fresh while its created_at is stale.

The oracle is the pre-rewrite algorithm itself (read the table, decide in
Python), so these fail if the SQL ever selects a different set.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, update

from app.core.workflow import _current_state, find_stale_entities
from app.support.models.tickets import Ticket, TicketStatus
from app.support.services.workflows import TICKET_WORKFLOW as SPEC

T = "tenant_stale_sql"


async def _oracle(db, spec, tenant_id, limit=100):
    """The pre-rewrite implementation, verbatim: scan, then decide in Python."""
    now = datetime.now(timezone.utc)
    q = await db.execute(select(spec.model).where(spec.model.tenant_id == tenant_id).limit(2000))
    out = []
    for obj in q.scalars().all():
        state = _current_state(obj, spec)
        max_hours = spec.sla_hours.get(state)
        if max_hours is None:
            continue
        stamp = getattr(obj, "updated_at", None) or getattr(obj, "created_at", None)
        if stamp is None:
            continue
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        if (now - stamp).total_seconds() / 3600.0 > max_hours:
            out.append(obj.id)
    return out[:limit]


async def _add(db, status, created_at, updated_at, tenant_id=T):
    """Insert then backdate: created_at/updated_at carry server defaults and
    onupdate, so they have to be written after the flush."""
    tid = str(uuid.uuid4())
    db.add(Ticket(id=tid, tenant_id=tenant_id, ticket_number=f"T-{uuid.uuid4().hex[:10]}",
                  subject="s", description="d", status=TicketStatus(status)))
    await db.commit()
    await db.execute(update(Ticket).where(Ticket.id == tid)
                     .values(created_at=created_at, updated_at=updated_at))
    await db.commit()
    db.expire_all()
    return tid


@pytest.mark.asyncio
async def test_sql_predicate_matches_python_oracle_on_edge_cases(db):
    state, hours = "NEW", SPEC.sla_hours["NEW"]
    now = datetime.now(timezone.utc)
    old = now - timedelta(hours=hours + 24)
    fresh = now - timedelta(minutes=1)

    ids = {
        # updated_at NULL -> falls back to created_at (the coalesce path)
        "null_upd_stale": await _add(db, state, old, None),
        "null_upd_fresh": await _add(db, state, fresh, None),
        # updated_at fresh over a stale created_at -> NOT a breach
        "touched": await _add(db, state, old, fresh),
        # updated_at stale over a fresh created_at -> breach
        "stale_touch": await _add(db, state, fresh, old),
        # naive timestamps, which the old loop read as UTC
        "naive_stale": await _add(db, state, old.replace(tzinfo=None), None),
        # no timestamps at all -> never a breach
        "no_stamp": await _add(db, state, None, None),
    }

    got = set(b["entity_id"] for b in await find_stale_entities(db, SPEC, T))
    want = set(await _oracle(db, SPEC, T))
    assert want, "fixture produced no breaches, so this would assert nothing"
    assert got == want, (
        "SQL predicate disagrees with the Python oracle on "
        f"{[k for k, v in ids.items() if v in got ^ want]}"
    )
    # Pin the expectation too, so a bug in both paths still shows up.
    assert got == {ids["null_upd_stale"], ids["stale_touch"], ids["naive_stale"]}


@pytest.mark.asyncio
async def test_breach_is_tenant_scoped(db):
    """The rewrite must not have widened the tenant filter."""
    old = datetime.now(timezone.utc) - timedelta(hours=SPEC.sla_hours["NEW"] + 48)
    mine = await _add(db, "NEW", old, old)
    theirs = await _add(db, "NEW", old, old, tenant_id="tenant_other_sql")

    ids = {b["entity_id"] for b in await find_stale_entities(db, SPEC, T)}
    assert mine in ids
    assert theirs not in ids


@pytest.mark.asyncio
async def test_state_without_an_sla_is_never_a_breach(db):
    """CLOSED has no sla_hours; an ancient CLOSED ticket must stay out."""
    assert "CLOSED" not in SPEC.sla_hours
    old = datetime.now(timezone.utc) - timedelta(days=90)
    row = await _add(db, "CLOSED", old, old)
    ids = {b["entity_id"] for b in await find_stale_entities(db, SPEC, T)}
    assert row not in ids
