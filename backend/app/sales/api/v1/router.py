"""
KAEOS Sales Domain — V1 API Router
CRUD and agent triggers.
"""
from app.core.tenant import get_tenant_id, require_role
from app.core.audit import record_security_event
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func as sqlfunc

from app.core.department_endpoints import (
    get_or_404, make_department_workflow_router, run_agent_endpoint,
)
from app.core.database import get_db

# Models
from app.sales.models.core import SalesRep
from app.sales.models.pipeline import Opportunity, OpportunityStage
from app.sales.models.leads import Lead, LeadScore
from app.sales.models.accounts import Account
from app.sales.models.forecasting import SalesForecast
# Single source of truth for "open" pipeline stages, so the dashboard's
# pipeline_total and /analytics' open_pipeline count the exact same stages
# (CLOSED_WON must not leak into open pipeline).
from app.sales.services.analytics import _OPEN_STAGES

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
        # Open pipeline only: excluding just CLOSED_LOST counted CLOSED_WON deals
        # as open, contradicting /analytics open_pipeline.
        .where(Opportunity.stage.in_(_OPEN_STAGES))
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
    # Latest score per lead in ONE query instead of one per row: order ascending
    # so the most recent row overwrites and wins in the dict.
    lead_ids = [l.id for l in leads]
    latest_score: dict = {}
    if lead_ids:
        scores_q = await db.execute(
            select(LeadScore.lead_id, LeadScore.overall_score)
            .where(LeadScore.tenant_id == tenant_id, LeadScore.lead_id.in_(lead_ids))
            .order_by(LeadScore.created_at.asc())
        )
        for lead_id, overall in scores_q.all():
            latest_score[lead_id] = overall
    lead_list = []
    for l in leads:
        lead_list.append({
            "id": l.id,
            "name": l.contact_name,
            "company": l.company,
            "email": l.email,
            "source": l.source.value if hasattr(l.source, 'value') else str(l.source),
            "status": "CONVERTED" if l.is_converted else "OPEN",
            "score": round((latest_score.get(l.id) or 0) / 20),  # 0-100 → 0-5 stars
        })
    return lead_list

# REVIEW: sales, legal and support pass actor=tenant.get("name"), which is
# None for any principal without a name, so the gated execution lands in the
# audit ledger unattributed. engineering and operations use
# approver_identity(tenant) instead. Drift preserved - see
# app/core/department_endpoints.py.
@router.post("/leads/{lead_id}/score")
async def score_lead(lead_id: str, tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db)):
    return await run_agent_endpoint(
        LeadScoringAgent().score_lead(db, lead_id, tenant["tenant_id"]), tenant,
        actor=tenant.get("name"), resource_type="lead", resource_id=lead_id, logger=logger,
    )

# --- Accounts ---
@router.get("/accounts")
async def list_accounts(
    tenant_id: str = Depends(get_tenant_id),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    q = await db.execute(select(Account).where(Account.tenant_id == tenant_id).limit(limit).offset(offset))
    accounts = q.scalars().all()
    # Resolve rep names once, not per row.
    rep_ids = {a.assigned_rep_id for a in accounts if a.assigned_rep_id}
    rep_names = {}
    if rep_ids:
        r_q = await db.execute(select(SalesRep.id, SalesRep.name).where(
            SalesRep.tenant_id == tenant_id, SalesRep.id.in_(rep_ids)))
        rep_names = {rid: name for rid, name in r_q.all()}
    result = []
    for a in accounts:
        rep_name = rep_names.get(a.assigned_rep_id)
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
    return await run_agent_endpoint(
        AccountHealthAgent().assess_health(db, account_id, tenant["tenant_id"]), tenant,
        actor=tenant.get("name"), resource_type="account", resource_id=account_id, logger=logger,
    )


@router.post("/accounts/{account_id}/churn-risk")
async def assess_churn_risk(account_id: str, tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db)):
    return await run_agent_endpoint(
        ChurnAgent().identify_churn_risk(db, account_id, tenant["tenant_id"]), tenant,
        actor=tenant.get("name"), resource_type="account", resource_id=account_id, logger=logger,
    )

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
    # Resolve account names once, not per row.
    account_ids = {o.account_id for o in opps if o.account_id}
    account_names = {}
    if account_ids:
        a_q = await db.execute(select(Account.id, Account.name).where(
            Account.tenant_id == tenant_id, Account.id.in_(account_ids)))
        account_names = {aid: name for aid, name in a_q.all()}
    result = []
    for o in opps:
        result.append({
            "id": o.id,
            "name": o.name,
            "account": account_names.get(o.account_id),
            "stage": o.stage.value if hasattr(o.stage, 'value') else str(o.stage),
            "value": float(o.amount or 0),
            "close_date": str(o.close_date) if o.close_date else None,
            "win_probability": float(o.ai_win_probability or o.probability or 0),
            "next_step": o.ai_next_step,
        })
    return result

@router.post("/opportunities/{opportunity_id}/coach")
async def coach_opportunity(opportunity_id: str, tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db)):
    return await run_agent_endpoint(
        PipelineCoachAgent().coach_opportunity(db, opportunity_id, tenant["tenant_id"]), tenant,
        actor=tenant.get("name"), resource_type="opportunity", resource_id=opportunity_id, logger=logger,
    )


@router.post("/opportunities/{opportunity_id}/proposal")
async def generate_proposal(opportunity_id: str, tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db)):
    """Always routes to HITL - a customer-facing document never ships unreviewed."""
    return await run_agent_endpoint(
        ProposalGenAgent().generate_proposal(db, opportunity_id, tenant["tenant_id"]), tenant,
        actor=tenant.get("name"), resource_type="opportunity", resource_id=opportunity_id, logger=logger,
    )

@router.post("/opportunities/{opportunity_id}/cpq")
async def cpq_review(opportunity_id: str, discount: float = Query(...), tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db)):
    return await run_agent_endpoint(
        CPQAgent().evaluate_quote(db, opportunity_id, discount, tenant["tenant_id"]), tenant,
        actor=tenant.get("name"), resource_type="opportunity", resource_id=opportunity_id, logger=logger,
    )

# --- Forecasts ---
@router.get("/forecasts")
async def list_forecasts(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    from app.sales.models.forecasting import ForecastLine
    q = await db.execute(select(SalesForecast).where(SalesForecast.tenant_id == tenant_id).limit(200))
    fcs = q.scalars().all()

    # Batch all forecast lines and their rep names once, instead of one query
    # per forecast plus one more per line.
    fc_ids = [f.id for f in fcs]
    lines_by_fc: dict = {}
    rep_ids = set()
    if fc_ids:
        lines_q = await db.execute(select(ForecastLine).where(
            ForecastLine.tenant_id == tenant_id, ForecastLine.forecast_id.in_(fc_ids)))
        for ln in lines_q.scalars().all():
            lines_by_fc.setdefault(ln.forecast_id, []).append(ln)
            if ln.rep_id:
                rep_ids.add(ln.rep_id)
    rep_names = {}
    if rep_ids:
        rep_q = await db.execute(select(SalesRep.id, SalesRep.name).where(
            SalesRep.tenant_id == tenant_id, SalesRep.id.in_(rep_ids)))
        rep_names = {rid: name for rid, name in rep_q.all()}

    result = []
    for f in fcs:
        lines = lines_by_fc.get(f.id, [])
        # Build one row per rep line, plus one aggregate row
        if lines:
            for ln in lines:
                result.append({
                    "id": ln.id,
                    "period": f.quarter,
                    "rep": rep_names.get(ln.rep_id),
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
    return await run_agent_endpoint(
        ForecastAgent().predict_forecast(db, forecast_id, tenant["tenant_id"]), tenant,
        actor=tenant.get("name"), resource_type="forecast", resource_id=forecast_id, logger=logger,
    )

# --- Commission ---
@router.get("/commission")
async def list_commission_calculations(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    """Commission calculations for this tenant, joined to the plan name so the
    UI never has to show a raw plan_id.

    This list had no endpoint at all: the only commission route was the payout
    POST, so callers (including an e2e test) had to reach into the database
    file directly to find an id.
    """
    from app.sales.models.commission import CommissionCalculation, CommissionPlan
    q = await db.execute(
        select(CommissionCalculation, CommissionPlan.plan_name)
        .outerjoin(CommissionPlan, (CommissionPlan.id == CommissionCalculation.plan_id)
                   & (CommissionPlan.tenant_id == tenant_id))
        .where(CommissionCalculation.tenant_id == tenant_id).limit(200)
    )
    return [
        {
            "id": c.id,
            "plan_id": c.plan_id,
            "plan_name": plan_name,
            "opportunity_id": c.opportunity_id,
            "deal_value": float(c.deal_value or 0),
            "calculated_payout": float(c.calculated_payout or 0),
            "is_approved": c.is_approved,
            "paid_date": str(c.paid_date) if c.paid_date else None,
        }
        for c, plan_name in q.all()
    ]


@router.post("/commission/{calculation_id}/payout")
async def calculate_commission(calculation_id: str, tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db)):
    return await run_agent_endpoint(
        CommissionAgent().calculate_payout(db, calculation_id, tenant["tenant_id"]), tenant,
        actor=tenant.get("name"), resource_type="commission_calculation", resource_id=calculation_id, logger=logger,
    )

# ═══════════════════════════════════════════════════════════════════════
# Analytics & Workflow Layer (shared engine: app.core.workflow)
# ═══════════════════════════════════════════════════════════════════════
from typing import Optional  # noqa: E402
from app.core.workflow import (  # noqa: E402
    TransitionRequest, apply_transition,
)
from app.sales.services.analytics import sales_analytics  # noqa: E402
from app.sales.services.workflows import SPECS as WORKFLOW_SPECS  # noqa: E402


@router.get("/analytics")
async def get_sales_analytics(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    """Computed pipeline, win-rate and account KPIs for the sales cockpit."""
    return await sales_analytics(db, tenant_id)


# Generated from the shared factory in app/core/department_endpoints.py.
# Endpoint names and docstrings are the hand-written originals, so the
# operationIds and descriptions in the OpenAPI schema are unchanged.
router.include_router(make_department_workflow_router(
    "sales", WORKFLOW_SPECS,
    workflows_doc='Declared state machines — the frontend renders stage actions from this.',
    events_doc='Tenant-scoped transition audit trail for sales entities.',
))


@router.post("/opportunities/{opportunity_id}/transition")
async def transition_opportunity(
    opportunity_id: str, body: TransitionRequest,
    tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    """Advance a deal through the pipeline or close it won/lost."""
    return await apply_transition(db, WORKFLOW_SPECS["opportunity"], opportunity_id,
                                  body.to_state, tenant, note=body.note)

# ═══════════════════════════════════════════════════════════════════════
# Entity Creation
# ═══════════════════════════════════════════════════════════════════════
from datetime import date as _date  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402


class OpportunityCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=256)
    amount: float = Field(0, ge=0)
    probability: float = Field(10, ge=0, le=100)
    close_date: Optional[_date] = None
    account_id: Optional[str] = None


@router.post("/opportunities", status_code=201)
async def create_opportunity(
    body: OpportunityCreate,
    tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    """Add a deal to the pipeline (starts in PROSPECTING)."""
    tenant_id = tenant["tenant_id"]
    o = Opportunity(
        tenant_id=tenant_id, name=body.name, amount=body.amount,
        probability=body.probability, close_date=body.close_date,
        account_id=body.account_id,
    )
    db.add(o)
    await db.commit()
    await db.refresh(o)
    await record_security_event(
        tenant_id=tenant_id, event_type="MODIFICATION", action="WRITE",
        actor=tenant.get("name"), actor_role=tenant.get("role"),
        resource_type="opportunity", resource_id=o.id,
    )
    return {"id": o.id, "name": o.name, "stage": o.stage.value if hasattr(o.stage, "value") else str(o.stage),
            "amount": float(o.amount or 0), "probability": o.probability}


router.include_router(make_department_workflow_router(
    "sales", WORKFLOW_SPECS,
    bulk_doc='Apply one transition to up to 200 sales entities; per-id outcomes.',
))

# ═══════════════════════════════════════════════════════════════════════
# Data Privacy (CCPA / TCPA / DSAR) — real fail-closed call sites for the
# deterministic checkers in app/compliance/checkers/crm.py, so "sales has
# CCPA/TCPA/DSAR compliance" is an exercised control, not just a registered
# checker no code path ever calls.
# ═══════════════════════════════════════════════════════════════════════
from typing import List as _List  # noqa: E402
from app.sales.services.privacy import (  # noqa: E402
    PrivacyCheckBlocked, check_contact, check_data_sale, check_dsar,
)


class LeadContactCheck(BaseModel):
    channel: str = Field(..., description="call, sms, text, autodial, or prerecorded")
    do_not_contact: Optional[_List[str]] = None
    consent: Optional[bool] = None


@router.post("/leads/{lead_id}/contact-check")
async def check_lead_contact(
    lead_id: str, body: LeadContactCheck,
    tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    """TCPA gate: verifies a lead can be called or texted before a rep or
    dialer reaches out. Fail-closed - a BLOCK stops the contact."""
    tenant_id = tenant["tenant_id"]
    lead = await get_or_404(db, Lead, lead_id, tenant_id, detail=f"Lead {lead_id} not found")
    try:
        verdict = await check_contact(db, tenant_id, lead=lead, channel=body.channel,
                                      do_not_contact=body.do_not_contact, consent=body.consent)
    except PrivacyCheckBlocked as e:
        raise HTTPException(403, detail={"message": str(e), "verdict": e.verdict}) from e
    return verdict


class AccountDataSaleCheck(BaseModel):
    opted_out_of_sale: bool


@router.post("/accounts/{account_id}/data-sale-check")
async def check_account_data_sale(
    account_id: str, body: AccountDataSaleCheck,
    tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    """CCPA gate: verifies an account's data can be shared with a partner
    (e.g. a data-enrichment vendor sync) before it runs."""
    tenant_id = tenant["tenant_id"]
    account = await get_or_404(db, Account, account_id, tenant_id, detail=f"Account {account_id} not found")
    try:
        verdict = await check_data_sale(db, tenant_id, account=account,
                                        opted_out_of_sale=body.opted_out_of_sale)
    except PrivacyCheckBlocked as e:
        raise HTTPException(403, detail={"message": str(e), "verdict": e.verdict}) from e
    return verdict


class DSARCheck(BaseModel):
    subject_type: str = Field(..., description="lead or account")
    subject_id: str
    regime: str = Field(..., description="GDPR or CCPA")
    request_date: _date
    fulfilled_date: Optional[_date] = None
    status: Optional[str] = None
    as_of: Optional[_date] = None


@router.post("/privacy/dsar-check")
async def check_dsar_request(
    body: DSARCheck, tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    """DSAR gate: verifies a data-subject access/deletion request for a lead
    or account is within its statutory response window (GDPR one calendar
    month, CCPA 45 days)."""
    tenant_id = tenant["tenant_id"]
    try:
        verdict = await check_dsar(
            db, tenant_id, subject_type=body.subject_type, subject_id=body.subject_id,
            regime=body.regime, request_date=str(body.request_date),
            fulfilled_date=str(body.fulfilled_date) if body.fulfilled_date else None,
            status=body.status, as_of=str(body.as_of) if body.as_of else None,
        )
    except PrivacyCheckBlocked as e:
        raise HTTPException(403, detail={"message": str(e), "verdict": e.verdict}) from e
    return verdict
