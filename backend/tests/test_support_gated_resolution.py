"""Support resolution + KB agents are gated; model self-report has no authority.

The exact bug, reproduced and fixed: ResolutionAgent called the LLM raw and set
``ticket.status = RESOLVED`` whenever the model's OWN json said resolved with
confidence > 0.85 — the model's self-reported confidence was the authority,
bypassing all seven gates (its governed sibling AutoResolveAgent is forced to
HITL at 0.79 on the same router). KBAgent wrote articles from a raw LLM call.
Both now route through run_gated_support_skill, and ticket state is never
changed by the agent.
"""
import uuid

from sqlalchemy import select

from app.support.agents.kb_agent import KBAgent
from app.support.agents.resolution_agent import ResolutionAgent
from app.support.models.knowledge import KBArticle
from app.support.models.tickets import Ticket, TicketComment, TicketStatus


def _t():
    return f"tenant_sup_{uuid.uuid4().hex[:6]}"


async def _mk_ticket(db, tenant_id):
    t = Ticket(tenant_id=tenant_id, ticket_number=f"T-{uuid.uuid4().hex[:5]}",
               subject="Printer on fire", description="It is very much on fire.",
               status=TicketStatus.OPEN)
    db.add(t)
    await db.commit()
    await db.refresh(t)
    return t


def _fake_gate(status, decision_json=None):
    async def fake_execute_skill(self, skill, ctx):
        chain = [{"decision": decision_json}] if decision_json else []
        return {"status": status, "reasoning_chain": chain,
                "execution_id": ctx.get("execution_id", "x")}
    return fake_execute_skill


async def test_resolution_agent_never_closes_ticket(db, monkeypatch):
    """Even a maximally confident model verdict must not flip ticket status."""
    from app.agents.runtime import AgentExecutor
    tenant = _t()
    ticket = await _mk_ticket(db, tenant)
    monkeypatch.setattr(AgentExecutor, "execute_skill", _fake_gate(
        "SUCCESS_CLEAN",
        '{"resolved": true, "confidence": 0.99, "article_matched": "None", '
        '"draft_reply": "Please power-cycle the printer."}'))

    result = await ResolutionAgent().solve_ticket(db, ticket.id, tenant)

    assert result["status"] == "SUCCESS_CLEAN"
    assert result["recommendation_only"] is True
    assert result["resolved"] is True          # the recommendation is surfaced
    fresh = (await db.execute(select(Ticket).where(Ticket.id == ticket.id))).scalar_one()
    assert fresh.status == TicketStatus.OPEN   # ...but the ticket did not move
    # The draft landed as an internal comment.
    comments = (await db.execute(select(TicketComment).where(
        TicketComment.ticket_id == ticket.id))).scalars().all()
    assert len(comments) == 1 and comments[0].is_internal == "Yes"


async def test_resolution_agent_pause_writes_nothing(db, monkeypatch):
    from app.agents.runtime import AgentExecutor
    tenant = _t()
    ticket = await _mk_ticket(db, tenant)
    monkeypatch.setattr(AgentExecutor, "execute_skill", _fake_gate("PENDING_HITL"))

    result = await ResolutionAgent().solve_ticket(db, ticket.id, tenant)

    assert result["status"] == "PENDING_HITL"
    assert result["resolved"] is False and result["draft_reply"] is None
    comments = (await db.execute(select(TicketComment).where(
        TicketComment.ticket_id == ticket.id))).scalars().all()
    assert comments == []


async def test_kb_agent_gated_and_always_unpublished(db, monkeypatch):
    from app.agents.runtime import AgentExecutor
    tenant = _t()
    ticket = await _mk_ticket(db, tenant)
    monkeypatch.setattr(AgentExecutor, "execute_skill", _fake_gate(
        "SUCCESS_CLEAN",
        '{"article_title": "How to unburn a printer", '
        '"content_markdown": "# Steps", "categories": ["technical_faq"]}'))

    result = await KBAgent().document_resolution(db, ticket.id, tenant)

    assert result["article_id"]
    art = (await db.execute(select(KBArticle).where(
        KBArticle.id == result["article_id"]))).scalar_one()
    assert art.is_published is False


async def test_kb_agent_blocked_persists_nothing(db, monkeypatch):
    from app.agents.runtime import AgentExecutor
    tenant = _t()
    ticket = await _mk_ticket(db, tenant)
    monkeypatch.setattr(AgentExecutor, "execute_skill", _fake_gate("BLOCKED_COMPLIANCE"))

    result = await KBAgent().document_resolution(db, ticket.id, tenant)

    assert result["article_id"] is None
    arts = (await db.execute(select(KBArticle).where(
        KBArticle.tenant_id == tenant))).scalars().all()
    assert arts == []


def test_resolution_skill_forced_to_hitl_threshold():
    """Customer-facing reply drafting carries the same 0.79 forced-HITL override
    as its sibling auto_resolve."""
    from app.agents.department_gate import SUPPORT
    assert SUPPORT.confidence_overrides["support_ticket_resolution"] == 0.79
