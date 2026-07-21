"""
KAEOS Sales Domain — V1 API Router
CRUD and agent triggers.
"""
from app.core.tenant import get_tenant_id, require_role
from app.core.audit import record_security_event
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func as sqlfunc

from app.core.database import get_db

# Models
from app.sales.models.core import SalesRep
from app.sales.models.pipeline import Opportunity, OpportunityStage
from app.sales.models.leads import Lead, LeadScore
from app.sales.models.accounts import Account
from app.sales.models.forecasting import SalesForecast

# Agents
from app.sales.agents.pipeline_coach_agent import PipelineCoachAgent
from app.sales.agents.proposal_gen_agent import ProposalGenAgent
from app.sales.agents.lead_scoring_agent import LeadScoringAgent
from app.sales.agents.forecast_agent import ForecastAgent
from app.sales.agents.commission_agent import CommissionAgent
from app.sales.agents.account_health_agent import AccountHealthAgent
from app.sales.agents.churn_agent import ChurnAgent
from app.sales.agents.cpq_agent import CPQAgent

import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sales", tags=["Sales"])

# --- Dashboard ---
@router.get("/dashboard")
async def sales_dashboard(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    # Pipeline
    pipeline_q = await db.execute(
        select(sqlfunc.coalesce(sqlfunc.sum(Opportunity.amount), 0))
        .select_from(Opportunity).where(Opportunity.tenant_id == tenant_id)
        .where(Opportunity.stage != OpportunityStage.CLOSED_LOST)
    )
    pipeline_total = float(pipeline_q.scalar() or 0.00)

    # Wins
    won_q = await db.execute(
        select(sqlfunc.coalesce(sqlfunc.sum(Opportunity.amount), 0))
        .select_from(Opportunity).where(Opportunity.tenant_id == tenant_id)
        .where(Opportunity.stage == OpportunityStage.CLOSED_WON)
    )
    total_won = float(won_q.scalar() or 0.00)

    # Open Leads
    leads_q = await db.execute(
        select(sqlfunc.count()).select_from(Lead).where(Lead.tenant_id == tenant_id)
        .where(Lead.is_converted == False)
    )
    open_leads = leads_q.scalar() or 0

    # Quota Attainment
    rep_q = await db.execute(
        select(sqlfunc.coalesce(sqlfunc.sum(SalesRep.quota_ytd), 0), sqlfunc.coalesce(sqlfunc.sum(SalesRep.attainment_ytd), 0))
        .select_from(SalesRep).where(SalesRep.tenant_id == tenant_id)
    )
    row = rep_q.one()
    quota, attainment = float(row[0] or 0.00), float(row[1] or 0.00)

    return {
        "pipeline_total": pipeline_total,
        "total_won": total_won,
        "open_leads": open_leads,
        "quota": quota,
        "attainment": attainment,
        "attainment_pct": round((attainment / quota * 100) if quota > 0 else 0.00, 1)
    }

# --- Leads ---
@router.get("/leads")
async def list_leads(
    tenant_id: str = Depends(get_tenant_id),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    q = await db.execute(select(Lead).where(Lead.tenant_id == tenant_id).limit(limit).offset(offset))
    leads = q.scalars().all()
    lead_list = []
    for l in leads:
        score_q = await db.execute(select(LeadScore).where(
            LeadScore.tenant_id == tenant_id, LeadScore.lead_id == l.id).order_by(LeadScore.created_at.desc()))
        score = score_q.scalars().first()
        lead_list.append({
            "id": l.id,
            "name": l.contact_name,
            "company": l.company,
            "email": l.email,
            "source": l.source.value if hasattr(l.source, 'value') else str(l.source),
            "status": "CONVERTED" if l.is_converted else "OPEN",
            "score": round((score.overall_score or 0) / 20) if score else 0,  # 0-100 → 0-5 stars
        })
    return lead_list

@router.post("/leads/{lead_id}/score")
async def score_lead(lead_id: str, tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db)):
    tenant_id = tenant["tenant_id"]
    agent = LeadScoringAgent()
    try:
        result = await agent.score_lead(db, lead_id, tenant_id)
        await record_security_event(
            tenant_id=tenant_id, event_type="MODIFICATION", action="EXECUTE",
            actor=tenant.get("name"), actor_role=tenant.get("role"),
            resource_type="lead", resource_id=lead_id,
        )
        return result
    except ValueError as e:
        raise HTTPException(404, detail=str(e))
    except Exception as e:
        logger.exception("%s failed", __name__)
        raise HTTPException(500, detail="Internal error - see server logs") from e

# --- Accounts ---
@router.get("/accounts")
async def list_accounts(
    tenant_id: str = Depends(get_tenant_id),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    from app.sales.models.core import SalesRep
    q = await db.execute(select(Account).where(Account.tenant_id == tenant_id).limit(limit).offset(offset))
    accounts = q.scalars().all()
    result = []
    for a in accounts:
        rep_name = None
        if a.assigned_rep_id:
            rep_q = await db.execute(select(SalesRep).where(
                SalesRep.id == a.assigned_rep_id, SalesRep.tenant_id == tenant_id))
            rep = rep_q.scalar_one_or_none()
            rep_name = rep.name if rep else None
        health_score = float(a.health_score or 0)
        health_label = "HEALTHY" if health_score >= 0.8 else ("AT_RISK" if health_score >= 0.5 else "CHURNED")
        result.append({
            "id": a.id,
            "name": a.name,
            "industry": a.industry,
            "arr": float(a.annual_recurring_revenue or 0),
            "health": health_label,
            "owner": rep_name,
            "last_activity": str(a.updated_at.date()) if getattr(a, 'updated_at', None) else None,
        })
    return result

@router.post("/accounts/{account_id}/health")
async def evaluate_account_health(account_id: str, tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db)):
    tenant_id = tenant["tenant_id"]
    agent = AccountHealthAgent()
    try:
        result = await agent.assess_health(db, account_id, tenant_id)
        await record_security_event(
            tenant_id=tenant_id, event_type="MODIFICATION", action="EXECUTE",
            actor=tenant.get("name"), actor_role=tenant.get("role"),
            resource_type="account", resource_id=account_id,
        )
        return result
    except ValueError as e:
        raise HTTPException(404, detail=str(e))
    except Exception as e:
        logger.exception("%s failed", __name__)
        raise HTTPException(500, detail="Internal error - see server logs") from e


@router.post("/accounts/{account_id}/churn-risk")
async def assess_churn_risk(account_id: str, tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db)):
    tenant_id = tenant["tenant_id"]
    agent = ChurnAgent()
    try:
        result = await agent.identify_churn_risk(db, account_id, tenant_id)
        await record_security_event(
            tenant_id=tenant_id, event_type="MODIFICATION", action="EXECUTE",
            actor=tenant.get("name"), actor_role=tenant.get("role"),
            resource_type="account", resource_id=account_id,
        )
        return result
    except ValueError as e:
        raise HTTPException(404, detail=str(e))
    except Exception as e:
        logger.exception("%s failed", __name__)
        raise HTTPException(500, detail="Internal error - see server logs") from e

# --- Opportunities ---
@router.get("/opportunities")
async def list_opportunities(
    tenant_id: str = Depends(get_tenant_id),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    q = await db.execute(select(Opportunity).where(Opportunity.tenant_id == tenant_id).limit(limit).offset(offset))
    opps = q.scalars().all()
    result = []
    for o in opps:
        account_name = None
        if o.account_id:
            acct_q = await db.execute(select(Account).where(
                Account.id == o.account_id, Account.tenant_id == tenant_id))
            acct = acct_q.scalar_one_or_none()
            account_name = acct.name if acct else None
        result.append({
            "id": o.id,
            "name": o.name,
            "account": account_name,
            "stage": o.stage.value if hasattr(o.stage, 'value') else str(o.stage),
            "value": float(o.amount or 0),
            "close_date": str(o.close_date) if o.close_date else None,
            "win_probability": float(o.ai_win_probability or o.probability or 0),
            "next_step": o.ai_next_step,
        })
    return result

@router.post("/opportunities/{opportunity_id}/coach")
async def coach_opportunity(opportunity_id: str, tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db)):
    tenant_id = tenant["tenant_id"]
    agent = PipelineCoachAgent()
    try:
        result = await agent.coach_opportunity(db, opportunity_id, tenant_id)
        await record_security_event(
            tenant_id=tenant_id, event_type="MODIFICATION", action="EXECUTE",
            actor=tenant.get("name"), actor_role=tenant.get("role"),
            resource_type="opportunity", resource_id=opportunity_id,
        )
        return result
    except ValueError as e:
        raise HTTPException(404, detail=str(e))
    except Exception as e:
        logger.exception("%s failed", __name__)
        raise HTTPException(500, detail="Internal error - see server logs") from e


@router.post("/opportunities/{opportunity_id}/proposal")
async def generate_proposal(opportunity_id: str, tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db)):
    """Always routes to HITL - a customer-facing document never ships unreviewed."""
    tenant_id = tenant["tenant_id"]
    agent = ProposalGenAgent()
    try:
        result = await agent.generate_proposal(db, opportunity_id, tenant_id)
        await record_security_event(
            tenant_id=tenant_id, event_type="MODIFICATION", action="EXECUTE",
            actor=tenant.get("name"), actor_role=tenant.get("role"),
            resource_type="opportunity", resource_id=opportunity_id,
        )
        return result
    except ValueError as e:
        raise HTTPException(404, detail=str(e))
    except Exception as e:
        logger.exception("%s failed", __name__)
        raise HTTPException(500, detail="Internal error - see server logs") from e

@router.post("/opportunities/{opportunity_id}/cpq")
async def cpq_review(opportunity_id: str, discount: float = Query(...), tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db)):
    tenant_id = tenant["tenant_id"]
    agent = CPQAgent()
    try:
        result = await agent.evaluate_quote(db, opportunity_id, discount, tenant_id)
        await record_security_event(
            tenant_id=tenant_id, event_type="MODIFICATION", action="EXECUTE",
            actor=tenant.get("name"), actor_role=tenant.get("role"),
            resource_type="opportunity", resource_id=opportunity_id,
        )
        return result
    except ValueError as e:
        raise HTTPException(404, detail=str(e))
    except Exception as e:
        logger.exception("%s failed", __name__)
        raise HTTPException(500, detail="Internal error - see server logs") from e

# --- Forecasts ---
@router.get("/forecasts")
async def list_forecasts(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    from app.sales.models.forecasting import ForecastLine
    q = await db.execute(select(SalesForecast).where(SalesForecast.tenant_id == tenant_id).limit(200))
    fcs = q.scalars().all()
    result = []
    for f in fcs:
        lines_q = await db.execute(select(ForecastLine).where(
            ForecastLine.tenant_id == tenant_id, ForecastLine.forecast_id == f.id))
        lines = lines_q.scalars().all()
        # Build one row per rep line, plus one aggregate row
        if lines:
            for ln in lines:
                rep_name = None
                if ln.rep_id:
                    from app.sales.models.core import SalesRep
                    rep_q = await db.execute(select(SalesRep).where(
                        SalesRep.id == ln.rep_id, SalesRep.tenant_id == tenant_id))
                    rep = rep_q.scalar_one_or_none()
                    rep_name = rep.name if rep else None
                result.append({
                    "id": ln.id,
                    "period": f.quarter,
                    "rep": rep_name,
                    "committed": float(ln.commit_amount or 0),
                    "best_case": float(ln.best_case_amount or 0),
                    "pipeline": float(ln.pipeline_amount or 0),
                    "quota": float(f.target_quota or 0),
                })
        else:
            result.append({
                "id": f.id,
                "period": f.quarter,
                "rep": "All Reps",
                "committed": float(f.commit_amount or 0),
                "best_case": float(f.best_case_amount or 0),
                "pipeline": float(f.pipeline_amount or 0),
                "quota": float(f.target_quota or 0),
            })
    return result

@router.post("/forecasts/{forecast_id}/predict")
async def predict_forecast(forecast_id: str, tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db)):
    tenant_id = tenant["tenant_id"]
    agent = ForecastAgent()
    try:
        result = await agent.predict_forecast(db, forecast_id, tenant_id)
        await record_security_event(
            tenant_id=tenant_id, event_type="MODIFICATION", action="EXECUTE",
            actor=tenant.get("name"), actor_role=tenant.get("role"),
            resource_type="forecast", resource_id=forecast_id,
        )
        return result
    except ValueError as e:
        raise HTTPException(404, detail=str(e))
    except Exception as e:
        logger.exception("%s failed", __name__)
        raise HTTPException(500, detail="Internal error - see server logs") from e

# --- Commission ---
@router.get("/commission")
async def list_commission_calculations(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    """Commission calculations for this tenant.

    This list had no endpoint at all: the only commission route was the payout
    POST, so callers (including an e2e test) had to reach into the database
    file directly to find an id.
    """
    from app.sales.models.commission import CommissionCalculation
    q = await db.execute(
        select(CommissionCalculation).where(CommissionCalculation.tenant_id == tenant_id).limit(200)
    )
    return [
        {
            "id": c.id,
            "plan_id": c.plan_id,
            "opportunity_id": c.opportunity_id,
            "deal_value": float(c.deal_value or 0),
            "calculated_payout": float(c.calculated_payout or 0),
            "is_approved": c.is_approved,
            "paid_date": str(c.paid_date) if c.paid_date else None,
        }
        for c in q.scalars().all()
    ]


@router.post("/commission/{calculation_id}/payout")
async def calculate_commission(calculation_id: str, tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db)):
    tenant_id = tenant["tenant_id"]
    agent = CommissionAgent()
    try:
        result = await agent.calculate_payout(db, calculation_id, tenant_id)
        await record_security_event(
            tenant_id=tenant_id, event_type="MODIFICATION", action="EXECUTE",
            actor=tenant.get("name"), actor_role=tenant.get("role"),
            resource_type="commission_calculation", resource_id=calculation_id,
        )
        return result
    except ValueError as e:
        raise HTTPException(404, detail=str(e))
    except Exception as e:
        logger.exception("%s failed", __name__)
        raise HTTPException(500, detail="Internal error - see server logs") from e

# ═══════════════════════════════════════════════════════════════════════
# Analytics & Workflow Layer (shared engine: app.core.workflow)
# ═══════════════════════════════════════════════════════════════════════
from typing import Optional  # noqa: E402
from app.core.workflow import TransitionRequest, apply_transition, list_workflow_events  # noqa: E402
from app.sales.services.analytics import sales_analytics  # noqa: E402
from app.sales.services.workflows import SPECS as WORKFLOW_SPECS  # noqa: E402


@router.get("/analytics")
async def get_sales_analytics(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    """Computed pipeline, win-rate and account KPIs for the sales cockpit."""
    return await sales_analytics(db, tenant_id)


@router.get("/workflows")
async def get_sales_workflows(tenant_id: str = Depends(get_tenant_id)):
    """Declared state machines — the frontend renders stage actions from this."""
    return {name: spec.describe() for name, spec in WORKFLOW_SPECS.items()}


@router.get("/workflow-events")
async def get_sales_workflow_events(
    entity_type: Optional[str] = None, entity_id: Optional[str] = None,
    tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db),
):
    """Tenant-scoped transition audit trail for sales entities."""
    return await list_workflow_events(db, tenant_id, domain="sales",
                                      entity_type=entity_type, entity_id=entity_id)


@router.post("/opportunities/{opportunity_id}/transition")
async def transition_opportunity(
    opportunity_id: str, body: TransitionRequest,
    tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    """Advance a deal through the pipeline or close it won/lost."""
    return await apply_transition(db, WORKFLOW_SPECS["opportunity"], opportunity_id,
                                  body.to_state, tenant, note=body.note)
