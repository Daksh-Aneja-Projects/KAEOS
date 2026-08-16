"""
KAEOS Support Domain — V1 API Router
CRUD and agent triggers.
"""
from app.core.tenant import get_tenant_id, require_role
from app.core.audit import record_security_event
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func as sqlfunc

from app.core.database import get_db

# Models
from app.support.models.core import SupportAgent, SupportTeam, SupportChannel
from app.support.models.tickets import Ticket, TicketComment, TicketStatus, TicketTag
from app.support.models.sla import SLAPolicy
from app.support.models.knowledge import ArticleFeedback, KBArticle, KBCategory
from app.support.models.feedback import CustomerSatisfaction, FeedbackTheme, NPS_Survey
from app.support.models.escalation import EscalationEvent, EscalationRule

# Agents
from app.support.agents.triage_agent import TriageAgent
from app.support.agents.resolution_agent import ResolutionAgent
from app.support.agents.kb_agent import KBAgent
from app.support.agents.sla_agent import SLAAgent
from app.support.agents.escalation_agent import EscalationAgent
from app.support.agents.auto_resolve_agent import AutoResolveAgent
from app.support.agents.csat_agent import CSATAgent

# Reuse the same hours-between math support_analytics() already uses for
# MTTR/first-response, so SLA compliance is computed identically everywhere.
from app.support.services.analytics import _hours_between

import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/support", tags=["Support"])


# --- Shared helpers ---
async def _customer_names(db: AsyncSession, tenant_id: str) -> dict:
    """Resolve customer_code ("CST001") -> display name once per request.
    Reused by every endpoint that surfaces a customer to a human instead of
    the internal code (list_tickets first fixed this; every other endpoint
    that names a customer reuses this instead of re-inventing it)."""
    from app.finance.models.accounts_receivable import Customer
    q = await db.execute(
        select(Customer.customer_code, Customer.name).where(Customer.tenant_id == tenant_id)
    )
    return {code: name for code, name in q.all()}


# --- Dashboard ---
@router.get("/dashboard")
async def support_dashboard(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    # Tickets
    total_q = await db.execute(select(sqlfunc.count()).select_from(Ticket).where(Ticket.tenant_id == tenant_id))
    total_tickets = total_q.scalar() or 0

    open_q = await db.execute(
        select(sqlfunc.count()).select_from(Ticket).where(Ticket.tenant_id == tenant_id)
        .where(Ticket.status.in_([TicketStatus.NEW, TicketStatus.ASSIGNED, TicketStatus.OPEN]))
    )
    open_tickets = open_q.scalar() or 0

    # Articles
    kb_q = await db.execute(select(sqlfunc.count()).select_from(KBArticle).where(KBArticle.tenant_id == tenant_id))
    kb_count = kb_q.scalar() or 0

    # CSAT
    csat_q = await db.execute(
        select(sqlfunc.coalesce(sqlfunc.avg(CustomerSatisfaction.rating), 0))
        .select_from(CustomerSatisfaction).where(CustomerSatisfaction.tenant_id == tenant_id)
    )
    avg_csat = float(csat_q.scalar() or 0.00)

    return {
        "total_tickets": total_tickets,
        "open_tickets": open_tickets,
        "kb_articles": kb_count,
        "avg_csat": round(avg_csat, 2)
    }

# --- Tickets ---
@router.get("/tickets")
async def list_tickets(
    tenant_id: str = Depends(get_tenant_id),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    q = await db.execute(select(Ticket).where(Ticket.tenant_id == tenant_id).limit(limit).offset(offset))
    tickets = q.scalars().all()
    # Resolve customer codes to names once, not per row: the list rendered a
    # raw "CST001" in the Customer column - an id no human recognises, when
    # the record ("Stark Industries") was one join away.
    customer_names = await _customer_names(db, tenant_id)

    result = []
    for t in tickets:
        agent_name = None
        if t.assigned_agent_id:
            agent_q = await db.execute(select(SupportAgent).where(
                SupportAgent.id == t.assigned_agent_id, SupportAgent.tenant_id == tenant_id
            ))
            agent = agent_q.scalar_one_or_none()
            agent_name = agent.name if agent else None
        result.append({
            "id": t.id,
            "subject": t.subject,
            "status": t.status.value if hasattr(t.status, 'value') else str(t.status),
            "priority": t.priority.value if hasattr(t.priority, 'value') else str(t.priority),
            "customer": customer_names.get(t.customer_id, t.customer_id),
            "customer_code": t.customer_id,
            "assignee": agent_name,
            "created_at": str(t.created_at) if t.created_at else None,
        })
    return result

@router.post("/tickets/{ticket_id}/triage")
async def triage_ticket(ticket_id: str, tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db)):
    tenant_id = tenant["tenant_id"]
    agent = TriageAgent()
    try:
        result = await agent.triage_ticket(db, ticket_id, tenant_id)
        await record_security_event(
            tenant_id=tenant_id, event_type="MODIFICATION", action="EXECUTE",
            actor=tenant.get("name"), actor_role=tenant.get("role"),
            resource_type="ticket", resource_id=ticket_id,
        )
        return result
    except ValueError as e:
        raise HTTPException(404, detail=str(e))
    except Exception as e:
        logger.exception("%s failed", __name__)
        raise HTTPException(500, detail="Internal error - see server logs") from e

@router.post("/tickets/{ticket_id}/solve")
async def solve_ticket(ticket_id: str, tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db)):
    tenant_id = tenant["tenant_id"]
    agent = ResolutionAgent()
    try:
        result = await agent.solve_ticket(db, ticket_id, tenant_id)
        await record_security_event(
            tenant_id=tenant_id, event_type="MODIFICATION", action="EXECUTE",
            actor=tenant.get("name"), actor_role=tenant.get("role"),
            resource_type="ticket", resource_id=ticket_id,
        )
        return result
    except ValueError as e:
        raise HTTPException(404, detail=str(e))
    except Exception as e:
        logger.exception("%s failed", __name__)
        raise HTTPException(500, detail="Internal error - see server logs") from e

@router.post("/tickets/{ticket_id}/auto-resolve")
async def auto_resolve_ticket(ticket_id: str, tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db)):
    """Draft a customer response - always pauses for human review (0.79 gate)."""
    tenant_id = tenant["tenant_id"]
    agent = AutoResolveAgent()
    try:
        result = await agent.generate_response(db, ticket_id, tenant_id)
        await record_security_event(
            tenant_id=tenant_id, event_type="MODIFICATION", action="EXECUTE",
            actor=tenant.get("name"), actor_role=tenant.get("role"),
            resource_type="ticket", resource_id=ticket_id,
        )
        return result
    except ValueError as e:
        raise HTTPException(404, detail=str(e))
    except Exception as e:
        logger.exception("%s failed", __name__)
        raise HTTPException(500, detail="Internal error - see server logs") from e

@router.post("/tickets/{ticket_id}/document")
async def document_resolution(ticket_id: str, tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db)):
    tenant_id = tenant["tenant_id"]
    agent = KBAgent()
    try:
        result = await agent.document_resolution(db, ticket_id, tenant_id)
        await record_security_event(
            tenant_id=tenant_id, event_type="MODIFICATION", action="EXECUTE",
            actor=tenant.get("name"), actor_role=tenant.get("role"),
            resource_type="ticket", resource_id=ticket_id,
        )
        return result
    except ValueError as e:
        raise HTTPException(404, detail=str(e))
    except Exception as e:
        logger.exception("%s failed", __name__)
        raise HTTPException(500, detail="Internal error - see server logs") from e

@router.post("/tickets/{ticket_id}/escalate")
async def escalate_ticket(ticket_id: str, tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db)):
    tenant_id = tenant["tenant_id"]
    agent = EscalationAgent()
    try:
        result = await agent.escalate_ticket(db, ticket_id, tenant_id)
        await record_security_event(
            tenant_id=tenant_id, event_type="MODIFICATION", action="EXECUTE",
            actor=tenant.get("name"), actor_role=tenant.get("role"),
            resource_type="ticket", resource_id=ticket_id,
        )
        return result
    except ValueError as e:
        raise HTTPException(404, detail=str(e))
    except Exception as e:
        logger.exception("%s failed", __name__)
        raise HTTPException(500, detail="Internal error - see server logs") from e


@router.get("/tickets/{ticket_id}/comments")
async def list_ticket_comments(
    ticket_id: str, tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db),
):
    """The actual support conversation thread (customer messages, agent
    replies, system entries) - written by ResolutionAgent/KBAgent today but
    never surfaced anywhere until now."""
    ticket_q = await db.execute(select(Ticket).where(Ticket.id == ticket_id, Ticket.tenant_id == tenant_id))
    if not ticket_q.scalar_one_or_none():
        raise HTTPException(404, detail=f"Ticket {ticket_id} not found")

    q = await db.execute(
        select(TicketComment).where(TicketComment.ticket_id == ticket_id, TicketComment.tenant_id == tenant_id)
        .order_by(TicketComment.created_at.asc())
    )
    comments = q.scalars().all()

    agent_ids = {c.author_id for c in comments if c.author_type == "AGENT" and c.author_id}
    agent_names = {}
    if agent_ids:
        a_q = await db.execute(select(SupportAgent.id, SupportAgent.name).where(
            SupportAgent.tenant_id == tenant_id, SupportAgent.id.in_(agent_ids)
        ))
        agent_names = {aid: name for aid, name in a_q.all()}
    customer_names = await _customer_names(db, tenant_id)

    def _author(c: TicketComment) -> str:
        if c.author_type == "AGENT":
            if c.author_id in agent_names:
                return agent_names[c.author_id]
            # Agents write internal comments under a fixed service id
            # ("resolution_agent") rather than a real SupportAgent row.
            if c.author_id == "resolution_agent":
                return "KAEOS Resolution Agent"
            return "Support Agent"
        if c.author_type == "CUSTOMER":
            return customer_names.get(c.author_id, c.author_id) or "Customer"
        return "System"

    return [{
        "id": c.id,
        "author_type": c.author_type,
        "author": _author(c),
        "body": c.body,
        "is_internal": c.is_internal == "Yes",
        "created_at": str(c.created_at) if c.created_at else None,
    } for c in comments]


@router.get("/tickets/{ticket_id}/tags")
async def list_ticket_tags(
    ticket_id: str, tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db),
):
    ticket_q = await db.execute(select(Ticket.id).where(Ticket.id == ticket_id, Ticket.tenant_id == tenant_id))
    if not ticket_q.scalar_one_or_none():
        raise HTTPException(404, detail=f"Ticket {ticket_id} not found")
    q = await db.execute(select(TicketTag).where(TicketTag.ticket_id == ticket_id, TicketTag.tenant_id == tenant_id))
    return [{"id": t.id, "tag": t.tag} for t in q.scalars().all()]


# --- Teams & Channels ---
@router.get("/teams")
async def list_support_teams(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    teams_q = await db.execute(select(SupportTeam).where(SupportTeam.tenant_id == tenant_id))
    teams = teams_q.scalars().all()
    counts_q = await db.execute(
        select(SupportAgent.team_id, sqlfunc.count())
        .where(SupportAgent.tenant_id == tenant_id, SupportAgent.team_id.isnot(None))
        .group_by(SupportAgent.team_id)
    )
    counts = {tid: int(c) for tid, c in counts_q.all()}
    return [{
        "id": t.id, "name": t.name, "description": t.description, "tier": t.tier,
        "agent_count": counts.get(t.id, 0),
    } for t in teams]


@router.get("/channels")
async def list_support_channels(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    ch_q = await db.execute(select(SupportChannel).where(SupportChannel.tenant_id == tenant_id))
    channels = ch_q.scalars().all()
    team_ids = {c.routing_team_id for c in channels if c.routing_team_id}
    team_names = {}
    if team_ids:
        t_q = await db.execute(select(SupportTeam.id, SupportTeam.name).where(
            SupportTeam.tenant_id == tenant_id, SupportTeam.id.in_(team_ids)
        ))
        team_names = {tid: name for tid, name in t_q.all()}
    return [{
        "id": c.id, "name": c.channel_name,
        "type": c.channel_type.value if hasattr(c.channel_type, "value") else str(c.channel_type),
        "routing_team": team_names.get(c.routing_team_id),
        "is_active": c.is_active,
    } for c in channels]


@router.get("/agents/leaderboard")
async def support_agent_leaderboard(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    """Per-agent CSAT and ticket load, computed live from CustomerSatisfaction
    joined through the ticket each agent was assigned. Persists the result
    onto SupportAgent.avg_csat so the column stays meaningful for any other
    reader; an agent with no completed surveys gets an honest null, not 0."""
    agents_q = await db.execute(
        select(SupportAgent).where(SupportAgent.tenant_id == tenant_id, SupportAgent.is_active == True)  # noqa: E712
    )
    agents = agents_q.scalars().all()
    if not agents:
        return []

    teams_q = await db.execute(select(SupportTeam.id, SupportTeam.name).where(SupportTeam.tenant_id == tenant_id))
    team_names = {tid: name for tid, name in teams_q.all()}

    ratings_q = await db.execute(
        select(Ticket.assigned_agent_id, CustomerSatisfaction.rating)
        .select_from(CustomerSatisfaction)
        .join(Ticket, Ticket.id == CustomerSatisfaction.ticket_id)
        .where(CustomerSatisfaction.tenant_id == tenant_id, Ticket.assigned_agent_id.isnot(None))
    )
    ratings_by_agent: dict = {}
    for agent_id, rating in ratings_q.all():
        ratings_by_agent.setdefault(agent_id, []).append(rating)

    load_q = await db.execute(
        select(Ticket.assigned_agent_id, sqlfunc.count())
        .where(Ticket.tenant_id == tenant_id, Ticket.assigned_agent_id.isnot(None))
        .group_by(Ticket.assigned_agent_id)
    )
    ticket_counts = {aid: int(c) for aid, c in load_q.all()}

    result = []
    for a in agents:
        ratings = ratings_by_agent.get(a.id, [])
        avg = round(sum(ratings) / len(ratings), 2) if ratings else None
        a.avg_csat = avg
        db.add(a)
        result.append({
            "id": a.id, "name": a.name, "team": team_names.get(a.team_id),
            "is_ai": a.is_ai, "avg_csat": avg, "survey_count": len(ratings),
            "ticket_count": ticket_counts.get(a.id, 0),
        })
    await db.commit()
    result.sort(key=lambda r: (r["avg_csat"] is None, -(r["avg_csat"] or 0)))
    return result

# --- KB ---
@router.get("/kb/articles")
async def list_kb_articles(
    tenant_id: str = Depends(get_tenant_id),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    q = await db.execute(select(KBArticle).where(KBArticle.tenant_id == tenant_id).limit(limit).offset(offset))
    articles = q.scalars().all()
    result = []
    for a in articles:
        cat_name = None
        if a.category_id:
            cat_q = await db.execute(select(KBCategory).where(
                KBCategory.id == a.category_id, KBCategory.tenant_id == tenant_id
            ))
            cat = cat_q.scalar_one_or_none()
            cat_name = cat.name if cat else None
        result.append({
            "id": a.id,
            "title": a.title,
            "category": cat_name,
            "status": "PUBLISHED" if a.is_published else "DRAFT",
            "views": a.views or 0,
            "helpful_pct": round(float(a.helpfulness_score or 0) * 20),  # 0-5 → 0-100%
            "updated_at": str(a.updated_at) if getattr(a, 'updated_at', None) else None,
        })
    return result


async def _set_kb_published(article_id: str, tenant: dict, db: AsyncSession, published: bool) -> dict:
    tenant_id = tenant["tenant_id"]
    q = await db.execute(select(KBArticle).where(KBArticle.id == article_id, KBArticle.tenant_id == tenant_id))
    article = q.scalar_one_or_none()
    if not article:
        raise HTTPException(404, detail=f"KB article {article_id} not found")
    article.is_published = published
    db.add(article)
    await db.commit()
    await record_security_event(
        tenant_id=tenant_id, event_type="MODIFICATION", action="WRITE",
        actor=tenant.get("name"), actor_role=tenant.get("role"),
        resource_type="kb_article", resource_id=article_id,
    )
    return {"id": article.id, "status": "PUBLISHED" if article.is_published else "DRAFT"}


@router.patch("/kb/articles/{article_id}/publish")
async def publish_kb_article(article_id: str, tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db)):
    """Puts an AI-drafted (or any) KB article in front of customers. Every
    article KBAgent writes starts is_published=False - this is the only path
    that ever flips it to True."""
    return await _set_kb_published(article_id, tenant, db, True)


@router.patch("/kb/articles/{article_id}/unpublish")
async def unpublish_kb_article(article_id: str, tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db)):
    return await _set_kb_published(article_id, tenant, db, False)


@router.get("/kb/articles/{article_id}/feedback")
async def list_kb_article_feedback(
    article_id: str, tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db),
):
    art_q = await db.execute(select(KBArticle.id).where(KBArticle.id == article_id, KBArticle.tenant_id == tenant_id))
    if not art_q.scalar_one_or_none():
        raise HTTPException(404, detail=f"KB article {article_id} not found")
    q = await db.execute(
        select(ArticleFeedback).where(ArticleFeedback.article_id == article_id, ArticleFeedback.tenant_id == tenant_id)
        .order_by(ArticleFeedback.created_at.desc())
    )
    return [{
        "id": f.id, "is_helpful": f.is_helpful, "comment": f.comment,
        "created_at": str(f.created_at) if f.created_at else None,
    } for f in q.scalars().all()]

# --- CSAT ---
@router.get("/csat/surveys")
async def list_csat_surveys(
    tenant_id: str = Depends(get_tenant_id),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    q = await db.execute(select(CustomerSatisfaction).where(CustomerSatisfaction.tenant_id == tenant_id).limit(limit).offset(offset))
    surveys = q.scalars().all()

    # Resolve customer codes to names, the same fix already applied to
    # /tickets 30 lines above: CustomerSatisfaction -> Ticket -> Customer, one
    # batched lookup instead of a per-row query.
    ticket_ids = [s.ticket_id for s in surveys if s.ticket_id]
    ticket_customers = {}
    if ticket_ids:
        t_q = await db.execute(select(Ticket.id, Ticket.customer_id).where(
            Ticket.tenant_id == tenant_id, Ticket.id.in_(ticket_ids)
        ))
        ticket_customers = {tid: cid for tid, cid in t_q.all()}
    customer_names = await _customer_names(db, tenant_id)

    result = []
    for s in surveys:
        customer_code = ticket_customers.get(s.ticket_id)
        customer_name = customer_names.get(customer_code, customer_code) if customer_code else None
        result.append({
            "id": s.id,
            "customer": customer_name or "Anonymous",
            "rating": s.rating,
            "sentiment": s.sentiment,
            "ticket_id": s.ticket_id,
            "comment": s.comment,
            "created_at": str(s.created_at) if getattr(s, 'created_at', None) else None,
        })
    return result

@router.post("/csat/{survey_id}/analyze")
async def analyze_csat(survey_id: str, tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db)):
    tenant_id = tenant["tenant_id"]
    agent = CSATAgent()
    try:
        result = await agent.analyze_surveys(db, survey_id, tenant_id)
        await record_security_event(
            tenant_id=tenant_id, event_type="MODIFICATION", action="EXECUTE",
            actor=tenant.get("name"), actor_role=tenant.get("role"),
            resource_type="csat_survey", resource_id=survey_id,
        )
        return result
    except ValueError as e:
        raise HTTPException(404, detail=str(e))
    except Exception as e:
        logger.exception("%s failed", __name__)
        raise HTTPException(500, detail="Internal error - see server logs") from e


# --- NPS & Feedback Themes ---
@router.get("/nps/surveys")
async def list_nps_surveys(
    tenant_id: str = Depends(get_tenant_id),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    q = await db.execute(
        select(NPS_Survey).where(NPS_Survey.tenant_id == tenant_id)
        .order_by(NPS_Survey.created_at.desc()).limit(limit).offset(offset)
    )
    surveys = q.scalars().all()
    customer_names = await _customer_names(db, tenant_id)
    return [{
        "id": s.id,
        "customer": customer_names.get(s.customer_id, s.customer_id) or "Anonymous",
        "score": s.score,
        "feedback_text": s.feedback_text,
        "created_at": str(s.created_at) if s.created_at else None,
    } for s in surveys]


@router.get("/feedback/themes")
async def list_feedback_themes(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    q = await db.execute(
        select(FeedbackTheme).where(FeedbackTheme.tenant_id == tenant_id)
        .order_by(FeedbackTheme.volume_percentage.desc())
    )
    return [{
        "id": t.id, "theme": t.theme_name,
        "volume_pct": float(t.volume_percentage) if t.volume_percentage is not None else None,
        "severity": t.severity_rating,
    } for t in q.scalars().all()]


# --- Escalation ---
@router.get("/escalation-rules")
async def list_escalation_rules(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    q = await db.execute(select(EscalationRule).where(EscalationRule.tenant_id == tenant_id))
    rules = q.scalars().all()
    team_ids = {r.escalate_to_team_id for r in rules if r.escalate_to_team_id}
    agent_ids = {r.escalate_to_agent_id for r in rules if r.escalate_to_agent_id}
    team_names, agent_names = {}, {}
    if team_ids:
        t_q = await db.execute(select(SupportTeam.id, SupportTeam.name).where(
            SupportTeam.tenant_id == tenant_id, SupportTeam.id.in_(team_ids)
        ))
        team_names = {tid: name for tid, name in t_q.all()}
    if agent_ids:
        a_q = await db.execute(select(SupportAgent.id, SupportAgent.name).where(
            SupportAgent.tenant_id == tenant_id, SupportAgent.id.in_(agent_ids)
        ))
        agent_names = {aid: name for aid, name in a_q.all()}
    return [{
        "id": r.id, "name": r.rule_name, "trigger": r.trigger_condition,
        "escalate_to_team": team_names.get(r.escalate_to_team_id),
        "escalate_to_agent": agent_names.get(r.escalate_to_agent_id),
        "time_threshold_mins": r.time_threshold_mins, "is_active": r.is_active,
    } for r in rules]


@router.get("/escalation-events")
async def list_escalation_events(
    tenant_id: str = Depends(get_tenant_id),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    q = await db.execute(
        select(EscalationEvent).where(EscalationEvent.tenant_id == tenant_id)
        .order_by(EscalationEvent.created_at.desc()).limit(limit).offset(offset)
    )
    events = q.scalars().all()

    ticket_ids = {e.ticket_id for e in events if e.ticket_id}
    rule_ids = {e.rule_id for e in events if e.rule_id}
    agent_ids = ({e.escalated_from_agent_id for e in events if e.escalated_from_agent_id}
                 | {e.escalated_to_agent_id for e in events if e.escalated_to_agent_id})

    tickets_map = {}
    if ticket_ids:
        t_q = await db.execute(select(Ticket.id, Ticket.subject, Ticket.ticket_number).where(
            Ticket.tenant_id == tenant_id, Ticket.id.in_(ticket_ids)
        ))
        tickets_map = {tid: (subj, num) for tid, subj, num in t_q.all()}
    rules_map = {}
    if rule_ids:
        r_q = await db.execute(select(EscalationRule.id, EscalationRule.rule_name).where(
            EscalationRule.tenant_id == tenant_id, EscalationRule.id.in_(rule_ids)
        ))
        rules_map = {rid: name for rid, name in r_q.all()}
    agents_map = {}
    if agent_ids:
        a_q = await db.execute(select(SupportAgent.id, SupportAgent.name).where(
            SupportAgent.tenant_id == tenant_id, SupportAgent.id.in_(agent_ids)
        ))
        agents_map = {aid: name for aid, name in a_q.all()}

    result = []
    for e in events:
        t = tickets_map.get(e.ticket_id)
        result.append({
            "id": e.id,
            "ticket_id": e.ticket_id,
            "ticket_number": t[1] if t else None,
            "ticket_subject": t[0] if t else None,
            "rule": rules_map.get(e.rule_id),
            "from_agent": agents_map.get(e.escalated_from_agent_id),
            "to_agent": agents_map.get(e.escalated_to_agent_id),
            "reason": e.reason,
            "created_at": str(e.created_at) if e.created_at else None,
        })
    return result

# --- SLA ---
async def compute_sla_policy_metrics(db: AsyncSession, tenant_id: str) -> list:
    """Per-policy SLA compliance, computed live from each matching ticket's
    first_response_at/resolved_at against that policy's targets - never from
    a cached aggregate. A policy with no measurable tickets returns an honest
    null, not a fabricated number.

    Shared by GET /sla/metrics and the SLA Monitor agent so the two read the
    exact same live breach math (the agent used to read an always-empty
    sup_sla_breaches table instead)."""
    policies_q = await db.execute(select(SLAPolicy).where(SLAPolicy.tenant_id == tenant_id))
    policies = policies_q.scalars().all()
    if not policies:
        return []

    tickets_q = await db.execute(
        select(Ticket.priority, Ticket.created_at, Ticket.first_response_at, Ticket.resolved_at)
        .where(Ticket.tenant_id == tenant_id)
        .limit(2000)
    )
    all_tickets = tickets_q.all()

    result = []
    for p in policies:
        target_hours = round(p.response_target_mins / 60, 2)
        matched = [
            t for t in all_tickets
            if (t.priority.value if hasattr(t.priority, "value") else str(t.priority)) == p.priority_level
        ]
        responded = [t for t in matched if t.first_response_at is not None]
        # "Measurable" = at least one timestamp exists to judge against a
        # target; a ticket that is still brand-new with neither carries no
        # signal either way.
        measurable = [t for t in matched if t.first_response_at is not None or t.resolved_at is not None]

        if not measurable:
            result.append({
                "id": p.id, "policy": p.name, "priority": p.priority_level,
                "status": "NO_DATA", "target_hours": target_hours,
                "actual_hours": None, "compliance_pct": None, "breached_count": None,
                "note": "No tickets at this priority have a recorded first response or resolution yet.",
            })
            continue

        response_hours = [_hours_between(t.created_at, t.first_response_at) for t in responded]
        actual_hours = round(sum(response_hours) / len(response_hours), 2) if response_hours else None

        breached = 0
        for t in measurable:
            resp_breach = (t.first_response_at is not None
                           and _hours_between(t.created_at, t.first_response_at) > target_hours)
            reso_breach = (t.resolved_at is not None
                           and _hours_between(t.created_at, t.resolved_at) > p.resolution_target_hrs)
            if resp_breach or reso_breach:
                breached += 1
        compliance_pct = round((len(measurable) - breached) / len(measurable) * 100, 1)

        result.append({
            "id": p.id, "policy": p.name, "priority": p.priority_level,
            "status": "BREACHED" if compliance_pct < 90 else "MET",
            "target_hours": target_hours,
            "actual_hours": actual_hours,
            "compliance_pct": compliance_pct,
            "breached_count": breached,
        })
    return result


@router.get("/sla/metrics")
async def get_sla_metrics(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    """Per-policy SLA compliance, computed live from ticket timestamps."""
    return await compute_sla_policy_metrics(db, tenant_id)

@router.post("/sla/check")
async def check_sla(tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db)):
    tenant_id = tenant["tenant_id"]
    agent = SLAAgent()
    try:
        result = await agent.check_sla(db, tenant_id)
        await record_security_event(
            tenant_id=tenant_id, event_type="MODIFICATION", action="EXECUTE",
            actor=tenant.get("name"), actor_role=tenant.get("role"),
            resource_type="sla", resource_id=tenant_id,
        )
        return result
    except Exception as e:
        logger.exception("%s failed", __name__)
        raise HTTPException(500, detail="Internal error - see server logs") from e

# ═══════════════════════════════════════════════════════════════════════
# Analytics & Workflow Layer (shared engine: app.core.workflow)
# ═══════════════════════════════════════════════════════════════════════
from typing import Optional  # noqa: E402
from app.core.workflow import (  # noqa: E402
    BulkTransitionRequest, TransitionRequest, apply_bulk_transition,
    apply_transition, list_workflow_events,
)
from app.support.services.analytics import support_analytics  # noqa: E402
from app.support.services.workflows import SPECS as WORKFLOW_SPECS  # noqa: E402


@router.get("/analytics")
async def get_support_analytics(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    """Computed backlog, MTTR and first-response KPIs for the support cockpit."""
    return await support_analytics(db, tenant_id)


@router.get("/workflows")
async def get_support_workflows(tenant_id: str = Depends(get_tenant_id)):
    """Declared state machines - the frontend renders ticket actions from this."""
    return {name: spec.describe() for name, spec in WORKFLOW_SPECS.items()}


@router.get("/workflow-events")
async def get_support_workflow_events(
    entity_type: Optional[str] = None, entity_id: Optional[str] = None,
    tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db),
):
    """Tenant-scoped transition audit trail for support entities."""
    return await list_workflow_events(db, tenant_id, domain="support",
                                      entity_type=entity_type, entity_id=entity_id)


@router.post("/tickets/{ticket_id}/transition")
async def transition_ticket(
    ticket_id: str, body: TransitionRequest,
    tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    """Assign / resolve / close / reopen a ticket; stamps SLA timestamps."""
    return await apply_transition(db, WORKFLOW_SPECS["ticket"], ticket_id,
                                  body.to_state, tenant, note=body.note)

# ═══════════════════════════════════════════════════════════════════════
# Entity Creation
# ═══════════════════════════════════════════════════════════════════════
import uuid as _uuid_mod  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402


class TicketCreate(BaseModel):
    subject: str = Field(..., min_length=1, max_length=256)
    description: str = Field(..., min_length=1)
    priority: str = Field("MEDIUM", pattern="^(LOW|MEDIUM|HIGH|URGENT)$")
    customer_id: Optional[str] = None


@router.post("/tickets", status_code=201)
async def create_ticket(
    body: TicketCreate,
    tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    """Open a new support ticket (starts in NEW; lifecycle via /transition)."""
    tenant_id = tenant["tenant_id"]
    t = Ticket(
        tenant_id=tenant_id,
        ticket_number=f"T-{_uuid_mod.uuid4().hex[:8].upper()}",
        subject=body.subject,
        description=body.description,
        priority=body.priority,
        customer_id=body.customer_id,
    )
    db.add(t)
    await db.commit()
    await db.refresh(t)
    await record_security_event(
        tenant_id=tenant_id, event_type="MODIFICATION", action="WRITE",
        actor=tenant.get("name"), actor_role=tenant.get("role"),
        resource_type="ticket", resource_id=t.id,
    )
    return {"id": t.id, "number": t.ticket_number, "subject": t.subject,
            "status": t.status.value if hasattr(t.status, "value") else str(t.status),
            "priority": t.priority.value if hasattr(t.priority, "value") else str(t.priority)}


@router.post("/workflows/{entity_type}/bulk-transition")
async def bulk_transition_support(
    entity_type: str, body: BulkTransitionRequest,
    tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    """Apply one transition to up to 200 support entities; per-id outcomes."""
    spec = WORKFLOW_SPECS.get(entity_type)
    if not spec:
        raise HTTPException(404, detail=f"Unknown workflow entity '{entity_type}'. Known: {sorted(WORKFLOW_SPECS)}")
    return await apply_bulk_transition(db, spec, body.ids, body.to_state, tenant, note=body.note)
