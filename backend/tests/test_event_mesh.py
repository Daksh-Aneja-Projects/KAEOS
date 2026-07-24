"""v3 Phase 5 — Sense-Decide-Act Event Mesh.

Correlation is grounded in the real twin (departments that have skills); an
uncorrelated signal gets no action; severity drives the governed response kind.
"""
import uuid

import pytest

from app.models.domain import Skill
from app.models.event_mesh import ExternalSignal
from app.services import event_mesh

pytestmark = pytest.mark.asyncio


async def _seed(db, tenant, dept):
    db.add(Skill(id=str(uuid.uuid4()), skill_id=f"{dept}_skill_{uuid.uuid4().hex[:5]}",
                 tenant_id=tenant, department=dept, domain=dept, status="ACTIVE", confidence=0.9))
    await db.commit()


async def test_regulatory_kind_correlates_to_legal_via_prior(db):
    t = "tenant_em1"
    await _seed(db, t, "legal")
    s = ExternalSignal(tenant_id=t, kind="REGULATORY", title="New SEC disclosure rule", severity="warning")
    db.add(s)
    await event_mesh.correlate(db, t, s)
    assert any(m["name"] == "legal" for m in s.matched_entities)
    assert s.response_kind == "BRIEFING"
    assert s.status == "CORRELATED"


async def test_uncorrelated_signal_gets_no_action(db):
    t = "tenant_em2"
    await _seed(db, t, "finance")
    s = ExternalSignal(tenant_id=t, kind="NEWS", title="Unrelated celebrity gossip", severity="info")
    db.add(s)
    await event_mesh.correlate(db, t, s)
    assert s.matched_entities == []
    assert s.response_kind == "NONE"


async def test_critical_multi_department_triggers_mission(db):
    t = "tenant_em3"
    await _seed(db, t, "operations")
    await _seed(db, t, "finance")
    # Text names operations + finance (via 'finance' token) and kind prior = operations.
    s = ExternalSignal(tenant_id=t, kind="SUPPLY_CHAIN",
                       title="Key vendor outage hits operations and finance", severity="critical")
    db.add(s)
    await event_mesh.correlate(db, t, s)
    depts = {m["name"] for m in s.matched_entities if m["type"] == "department"}
    assert {"operations", "finance"} <= depts
    assert s.response_kind == "MISSION"


async def test_critical_single_department_triggers_hitl(db):
    t = "tenant_em4"
    await _seed(db, t, "engineering")
    s = ExternalSignal(tenant_id=t, kind="SECURITY", title="Critical CVE in a core dependency", severity="critical")
    db.add(s)
    await event_mesh.correlate(db, t, s)
    assert s.response_kind == "HITL"


async def test_respond_briefing_marks_responded(db):
    t = "tenant_em5"
    await _seed(db, t, "legal")
    s = ExternalSignal(tenant_id=t, kind="REGULATORY", title="GDPR guidance update", severity="warning")
    db.add(s)
    await event_mesh.correlate(db, t, s)
    await event_mesh.respond(db, t, s)
    assert s.status == "RESPONDED"
    assert s.responded_at is not None
