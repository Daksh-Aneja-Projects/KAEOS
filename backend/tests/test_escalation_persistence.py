"""§05 Escalation persistence — the SUCCESS_CLEAN + escalate branch.

The existing escalation test (test_support_fixes.py) stubs the gated runner to
PENDING_HITL, which structurally SKIPS the persistence branch in
``EscalationAgent.escalate_ticket``. This variant stubs the runner to return
SUCCESS_CLEAN with an ``escalate`` decision and asserts:
  * an EscalationEvent row is written for the ticket, and
  * the ticket's assigned agent is moved to the rule's escalate_to_agent_id.

If that persistence branch regresses (no event / no reassignment), these fail.
Runs on the in-memory unit harness; the runner is fully stubbed, so no LLM.
"""
import json
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

TENANT = "tenant_acme"


async def _ticket(db, assigned_agent_id):
    from app.support.models.tickets import Ticket, TicketPriority, TicketStatus
    t = Ticket(
        tenant_id=TENANT, ticket_number=f"T-{uuid.uuid4().hex[:10]}",
        subject="Cannot log in", description="Locked out since this morning",
        priority=TicketPriority.URGENT, status=TicketStatus.OPEN,
        assigned_agent_id=assigned_agent_id,
        created_at=datetime.now(timezone.utc),
    )
    db.add(t)
    await db.commit()
    await db.refresh(t)
    return t


@pytest.mark.asyncio
async def test_escalation_success_clean_persists_event_and_reassigns(db, monkeypatch):
    from app.support.agents.escalation_agent import EscalationAgent
    from app.support.models.core import SupportAgent
    from app.support.models.escalation import EscalationEvent, EscalationRule

    a_from = SupportAgent(tenant_id=TENANT, name="Tier 1", email="t1@kaeos.io")
    a_to = SupportAgent(tenant_id=TENANT, name="Tier 2", email="t2@kaeos.io")
    db.add_all([a_from, a_to])
    await db.commit()
    await db.refresh(a_from)
    await db.refresh(a_to)

    rule = EscalationRule(
        tenant_id=TENANT, rule_name="Urgent to Tier 2",
        trigger_condition="SLA_BREACH_RESPONSE", escalate_to_agent_id=a_to.id,
        time_threshold_mins=15, is_active=True,
    )
    db.add(rule)
    await db.commit()
    await db.refresh(rule)

    t = await _ticket(db, assigned_agent_id=a_from.id)
    ticket_id, from_id, to_id, rule_id = t.id, a_from.id, a_to.id, rule.id

    async def _fake_run_gated_support_skill(**kwargs):
        return {
            "status": "SUCCESS_CLEAN",
            "reasoning_chain": [{"decision": json.dumps({
                "escalate": True, "target_tier": "T2", "urgency": "high",
                "rationale": "Urgent auth outage, breaches response SLA.",
            })}],
        }

    import app.support.agents.escalation_agent as mod
    monkeypatch.setattr(mod, "run_gated_support_skill", _fake_run_gated_support_skill)

    result = await EscalationAgent().escalate_ticket(db, ticket_id, TENANT)
    assert result["status"] == "SUCCESS_CLEAN"

    db.expire_all()
    ev = (await db.execute(
        select(EscalationEvent).where(EscalationEvent.ticket_id == ticket_id)
    )).scalar_one()
    assert ev.rule_id == rule_id
    assert ev.escalated_from_agent_id == from_id
    assert ev.escalated_to_agent_id == to_id
    assert ev.reason

    from app.support.models.tickets import Ticket
    moved = (await db.execute(select(Ticket).where(Ticket.id == ticket_id))).scalar_one()
    assert moved.assigned_agent_id == to_id, "ticket must move to the rule's escalate_to agent"
