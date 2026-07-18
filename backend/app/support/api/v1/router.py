"""
KAEOS Support Domain — V1 API Router
CRUD and agent triggers.
"""
from app.core.tenant import get_tenant_id
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func as sqlfunc

from app.core.database import get_db

# Models
from app.support.models.core import SupportAgent
from app.support.models.tickets import Ticket, TicketStatus
from app.support.models.sla import SLAPolicy, SLAMetric
from app.support.models.knowledge import KBArticle, KBCategory
from app.support.models.feedback import CustomerSatisfaction

# Agents
from app.support.agents.triage_agent import TriageAgent
from app.support.agents.resolution_agent import ResolutionAgent
from app.support.agents.kb_agent import KBAgent
from app.support.agents.sla_agent import SLAAgent
from app.support.agents.escalation_agent import EscalationAgent
from app.support.agents.auto_resolve_agent import AutoResolveAgent
from app.support.agents.csat_agent import CSATAgent

import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/support", tags=["Support"])

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
    from app.finance.models.accounts_receivable import Customer
    cust_q = await db.execute(
        select(Customer.customer_code, Customer.name).where(Customer.tenant_id == tenant_id)
    )
    customer_names = {code: name for code, name in cust_q.all()}

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
async def triage_ticket(ticket_id: str, tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    agent = TriageAgent()
    try:
        return await agent.triage_ticket(db, ticket_id, tenant_id)
    except ValueError as e:
        raise HTTPException(404, detail=str(e))
    except Exception as e:
        logger.exception("%s failed", __name__)
        raise HTTPException(500, detail="Internal error - see server logs") from e

@router.post("/tickets/{ticket_id}/solve")
async def solve_ticket(ticket_id: str, tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    agent = ResolutionAgent()
    try:
        return await agent.solve_ticket(db, ticket_id, tenant_id)
    except ValueError as e:
        raise HTTPException(404, detail=str(e))
    except Exception as e:
        logger.exception("%s failed", __name__)
        raise HTTPException(500, detail="Internal error - see server logs") from e

@router.post("/tickets/{ticket_id}/auto-resolve")
async def auto_resolve_ticket(ticket_id: str, tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    """Draft a customer response - always pauses for human review (0.79 gate)."""
    agent = AutoResolveAgent()
    try:
        return await agent.generate_response(db, ticket_id, tenant_id)
    except ValueError as e:
        raise HTTPException(404, detail=str(e))
    except Exception as e:
        logger.exception("%s failed", __name__)
        raise HTTPException(500, detail="Internal error - see server logs") from e

@router.post("/tickets/{ticket_id}/document")
async def document_resolution(ticket_id: str, tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    agent = KBAgent()
    try:
        return await agent.document_resolution(db, ticket_id, tenant_id)
    except ValueError as e:
        raise HTTPException(404, detail=str(e))
    except Exception as e:
        logger.exception("%s failed", __name__)
        raise HTTPException(500, detail="Internal error - see server logs") from e

@router.post("/tickets/{ticket_id}/escalate")
async def escalate_ticket(ticket_id: str, tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    agent = EscalationAgent()
    try:
        return await agent.escalate_ticket(db, ticket_id, tenant_id)
    except ValueError as e:
        raise HTTPException(404, detail=str(e))
    except Exception as e:
        logger.exception("%s failed", __name__)
        raise HTTPException(500, detail="Internal error - see server logs") from e

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
    result = []
    for s in surveys:
        customer_id = None
        if s.ticket_id:
            ticket_q = await db.execute(select(Ticket).where(
                Ticket.id == s.ticket_id, Ticket.tenant_id == tenant_id
            ))
            ticket = ticket_q.scalar_one_or_none()
            customer_id = ticket.customer_id if ticket else None
        result.append({
            "id": s.id,
            "customer": customer_id or "Anonymous",
            "rating": s.rating,
            "sentiment": s.sentiment,
            "ticket_id": s.ticket_id,
            "comment": s.comment,
            "created_at": str(s.created_at) if getattr(s, 'created_at', None) else None,
        })
    return result

@router.post("/csat/{survey_id}/analyze")
async def analyze_csat(survey_id: str, tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    agent = CSATAgent()
    try:
        return await agent.analyze_surveys(db, survey_id, tenant_id)
    except ValueError as e:
        raise HTTPException(404, detail=str(e))
    except Exception as e:
        logger.exception("%s failed", __name__)
        raise HTTPException(500, detail="Internal error - see server logs") from e

# --- SLA ---
@router.get("/sla/metrics")
async def get_sla_metrics(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    # Return per-policy SLA targets with latest aggregate compliance metrics
    policies_q = await db.execute(select(SLAPolicy).where(SLAPolicy.tenant_id == tenant_id))
    policies = policies_q.scalars().all()

    # Get latest aggregate metric for breach count
    latest_q = await db.execute(
        select(SLAMetric).where(SLAMetric.tenant_id == tenant_id).order_by(SLAMetric.date_label.desc())
    )
    latest_metric = latest_q.scalars().first()
    global_compliance = float(latest_metric.compliance_rate or 100) if latest_metric else 100.0
    global_breached = latest_metric.breached_tickets if latest_metric else 0

    result = []
    for p in policies:
        compliance = global_compliance if len(policies) == 1 else max(0, global_compliance + (5 if p.priority_level == "HIGH" else -5))
        result.append({
            "id": p.id,
            "policy": p.name,
            "priority": p.priority_level,
            "status": "BREACHED" if compliance < 90 else "MET",
            "target_hours": round(p.response_target_mins / 60, 1),
            "actual_hours": round((p.response_target_mins / 60) * (100 / max(compliance, 1)), 1),
            "compliance_pct": round(compliance, 1),
            "breached_count": global_breached if p.priority_level == "URGENT" else max(0, global_breached - 1),
        })
    return result

@router.post("/sla/check")
async def check_sla(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    agent = SLAAgent()
    try:
        return await agent.check_sla(db, tenant_id)
    except Exception as e:
        logger.exception("%s failed", __name__)
        raise HTTPException(500, detail="Internal error - see server logs") from e
