"""
KAEOS Sales Domain — Database Seed Script
Seeds the Sales tables with realistic pipelines, reps, quota plans, and forecast targets.
"""
import asyncio
import uuid
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select

from app.core.database import async_engine, AsyncSessionLocal
from app.models.domain import Base

# Models imports
from app.sales.models.core import SalesRep, SalesTeam, Territory
from app.sales.models.pipeline import Opportunity, OpportunityProduct, OpportunityStage
from app.sales.models.leads import Lead, LeadScore, LeadSource
from app.sales.models.accounts import Account, Contact, AccountActivity
from app.sales.models.forecasting import SalesForecast, ForecastLine
from app.sales.models.commission import CommissionPlan, CommissionCalculation

TENANT = "tenant_acme"  # demo tenant — matches seed_demo_user and dev-mode tenant

def _id():
    return str(uuid.uuid4())


async def seed_tenant(db, tenant: str = TENANT) -> bool:
    """Seed the full sales domain for ``tenant`` in the given session.

    Idempotent: if the tenant already has a sales team, nothing is touched and
    False is returned. Returns True when a fresh seed ran.
    """
    already = (await db.execute(
        select(SalesTeam.id).where(SalesTeam.tenant_id == tenant).limit(1)
    )).scalar_one_or_none()
    if already is not None:
        print(f"[SKIP] Sales already seeded for {tenant}; leaving existing data untouched.")
        return False

    today = date.today()
    now = datetime.now(timezone.utc)

    # 1. Sales Teams
    teams = [
        SalesTeam(id=_id(), tenant_id=tenant, name="North America Enterprise", region="AMER", quota_annual=2500000.00),
        SalesTeam(id=_id(), tenant_id=tenant, name="EMEA Commercial", region="EMEA", quota_annual=1200000.00),
    ]
    for t in teams:
        db.add(t)
    await db.flush()

    # 2. Sales Reps
    reps = [
        SalesRep(id=_id(), tenant_id=tenant, name="Jim Halpert", email="jim.halpert@kaeos.io", team_id=teams[0].id, quota_ytd=600000.00, attainment_ytd=485000.00, is_active=True),
        SalesRep(id=_id(), tenant_id=tenant, name="Dwight Schrute", email="dwight.schrute@kaeos.io", team_id=teams[0].id, quota_ytd=800000.00, attainment_ytd=850000.00, is_active=True),
        SalesRep(id=_id(), tenant_id=tenant, name="Ryan Howard", email="ryan.howard@kaeos.io", team_id=teams[1].id, quota_ytd=300000.00, attainment_ytd=45000.00, is_active=True),
    ]
    for r in reps:
        db.add(r)
    await db.flush()

    # 3. Territories
    territories = [
        Territory(id=_id(), tenant_id=tenant, name="US West Enterprise", segment="ENTERPRISE", assigned_rep_id=reps[1].id),
        Territory(id=_id(), tenant_id=tenant, name="US East Enterprise", segment="ENTERPRISE", assigned_rep_id=reps[0].id),
    ]
    for tr in territories:
        db.add(tr)
    await db.flush()

    # 4. Accounts & Contacts
    accounts = [
        Account(id=_id(), tenant_id=tenant, name="Stark Industries", website="stark.com", industry="Defense", employee_count=12000, annual_recurring_revenue=250000.00, health_score=0.92, assigned_rep_id=reps[1].id),
        Account(id=_id(), tenant_id=tenant, name="Wayne Enterprises", website="wayne.corp", industry="Industrial", employee_count=45000, annual_recurring_revenue=150000.00, health_score=0.78, assigned_rep_id=reps[0].id),
        Account(id=_id(), tenant_id=tenant, name="Oscorp Industries", website="oscorp.com", industry="Biotechnology", employee_count=8200, annual_recurring_revenue=95000.00, health_score=0.88, assigned_rep_id=reps[0].id),
        Account(id=_id(), tenant_id=tenant, name="LexCorp Global", website="lexcorp.com", industry="Technology", employee_count=21000, annual_recurring_revenue=40000.00, health_score=0.18, assigned_rep_id=reps[2].id),
    ]
    for ac in accounts:
        db.add(ac)
    await db.flush()

    contacts = [
        Contact(id=_id(), tenant_id=tenant, account_id=accounts[0].id, first_name="Pepper", last_name="Potts", email="pepper@stark.com", phone="+1-212-555-1020", title="CEO"),
        Contact(id=_id(), tenant_id=tenant, account_id=accounts[1].id, first_name="Lucius", last_name="Fox", email="lucius@wayne.corp", phone="+1-312-555-4081", title="CEO"),
    ]
    for ct in contacts:
        db.add(ct)
    await db.flush()

    activities = [
        AccountActivity(id=_id(), tenant_id=tenant, account_id=accounts[0].id, activity_type="MEETING", subject="QBR Partnership Discussion", description="Reviewed platform utilization and planned SaaS node upgrades.", rep_id=reps[1].id),
        AccountActivity(id=_id(), tenant_id=tenant, account_id=accounts[1].id, activity_type="EMAIL", subject="Renewal Proposal Followup", description="Sent updated pricing for Wayne Corp node license renewal.", rep_id=reps[0].id),
    ]
    for act in activities:
        db.add(act)

    # 5. Opportunities & Products — one per funnel stage (including both closed
    # outcomes) so win-rate/avg-deal KPIs and every funnel bar render real data
    # on a fresh tenant instead of sitting at zero until a deal actually closes.
    opps = [
        Opportunity(id=_id(), tenant_id=tenant, name="Oscorp Industries Pilot Deployment", account_id=accounts[2].id, stage=OpportunityStage.PROSPECTING, amount=45000.00, probability=10.00, close_date=today + timedelta(days=90), assigned_rep_id=reps[0].id, ai_win_probability=22.00, ai_next_step="Qualify budget owner and technical stakeholder.", created_at=now - timedelta(days=3)),
        Opportunity(id=_id(), tenant_id=tenant, name="Wayne Industrial Core Node Upgrade", account_id=accounts[1].id, stage=OpportunityStage.QUALIFICATION, amount=85000.00, probability=40.00, close_date=today + timedelta(days=45), assigned_rep_id=reps[0].id, ai_win_probability=48.00, ai_next_step="Conduct executive presentation on technical topology.", created_at=now - timedelta(days=18)),
        Opportunity(id=_id(), tenant_id=tenant, name="Wayne Enterprises Disaster Recovery Suite", account_id=accounts[1].id, stage=OpportunityStage.PROPOSAL, amount=62000.00, probability=55.00, close_date=today + timedelta(days=30), assigned_rep_id=reps[0].id, ai_win_probability=58.00, ai_next_step="Send formal proposal with DR RTO/RPO commitments.", created_at=now - timedelta(days=10)),
        Opportunity(id=_id(), tenant_id=tenant, name="Stark Enterprise Platform Expansion", account_id=accounts[0].id, stage=OpportunityStage.NEGOTIATION, amount=150000.00, probability=85.00, close_date=today + timedelta(days=12), assigned_rep_id=reps[1].id, ai_win_probability=92.50, ai_next_step="Send legal redlines for SaaS contract review.", created_at=now - timedelta(days=25)),
        Opportunity(id=_id(), tenant_id=tenant, name="Stark Industries Global Rollout", account_id=accounts[0].id, stage=OpportunityStage.CLOSED_WON, amount=220000.00, probability=100.00, close_date=today - timedelta(days=20), assigned_rep_id=reps[1].id, ai_win_probability=100.00, ai_next_step="Kick off implementation with the Stark platform team.", created_at=now - timedelta(days=60)),
        Opportunity(id=_id(), tenant_id=tenant, name="LexCorp Global Trial Expansion", account_id=accounts[3].id, stage=OpportunityStage.CLOSED_LOST, amount=38000.00, probability=0.00, close_date=today - timedelta(days=35), assigned_rep_id=reps[2].id, ai_win_probability=8.00, ai_next_step="Closed lost: selected a lower-cost competitor at renewal.", created_at=now - timedelta(days=50)),
    ]
    for op in opps:
        db.add(op)
    await db.flush()

    products = [
        OpportunityProduct(id=_id(), tenant_id=tenant, opportunity_id=opps[3].id, product_name="KAEOS Node License", quantity=10, unit_price=15000.00),
        OpportunityProduct(id=_id(), tenant_id=tenant, opportunity_id=opps[1].id, product_name="Enterprise Integration Pack", quantity=1, unit_price=85000.00),
        OpportunityProduct(id=_id(), tenant_id=tenant, opportunity_id=opps[4].id, product_name="KAEOS Node License", quantity=14, unit_price=15714.29),
    ]
    for pr in products:
        db.add(pr)

    # 6. Leads & Lead Scores
    leads = [
        Lead(id=_id(), tenant_id=tenant, company="Oscorp Industries", contact_name="Harry Osborn", email="harry@oscorp.com", phone="+1-212-555-8812", source=LeadSource.WEBSITE, is_converted=False, assigned_rep_id=reps[1].id),
        Lead(id=_id(), tenant_id=tenant, company="LexCorp Global", contact_name="Mercy Graves", email="mercy@lexcorp.com", phone="+1-312-555-9081", source=LeadSource.OUTBOUND, is_converted=False, assigned_rep_id=reps[0].id),
    ]
    for ld in leads:
        db.add(ld)
    await db.flush()

    scores = [
        LeadScore(id=_id(), tenant_id=tenant, lead_id=leads[0].id, icp_score=95, intent_score=80, overall_score=88, factors="Inbound form submit, Matches scale parameters"),
        LeadScore(id=_id(), tenant_id=tenant, lead_id=leads[1].id, icp_score=68, intent_score=40, overall_score=54, factors="Outbound lead cold reach, Matches scale parameters"),
    ]
    for sc in scores:
        db.add(sc)

    # 7. Forecasts
    forecast = SalesForecast(
        id=_id(), tenant_id=tenant, quarter="Q3-2026", target_quota=1200000.00,
        commit_amount=850000.00, best_case_amount=1050000.00, pipeline_amount=2450000.00,
        ai_predicted_amount=1120000.00
    )
    db.add(forecast)
    await db.flush()

    fl = ForecastLine(
        id=_id(), tenant_id=tenant, forecast_id=forecast.id, rep_id=reps[1].id,
        commit_amount=600000.00, best_case_amount=700000.00, pipeline_amount=1500000.00
    )
    db.add(fl)

    # 8. Commission Plans & Calculations
    plans = [
        CommissionPlan(
            id=_id(), tenant_id=tenant, plan_name="AE Enterprise Commission Plan 2026",
            rep_id=reps[1].id, base_salary=120000.00, ote_target=240000.00,
            base_commission_rate=10.00, accelerator_threshold=100.00, accelerator_rate=15.00,
            is_active=True
        ),
        CommissionPlan(
            id=_id(), tenant_id=tenant, plan_name="AE Commercial Commission Plan 2026",
            rep_id=reps[0].id, base_salary=90000.00, ote_target=180000.00,
            base_commission_rate=8.00, accelerator_threshold=100.00, accelerator_rate=12.00,
            is_active=True
        ),
    ]
    for p in plans:
        db.add(p)
    await db.flush()

    calcs = [
        CommissionCalculation(
            id=_id(), tenant_id=tenant, plan_id=plans[0].id, opportunity_id=opps[3].id,
            deal_value=150000.00, calculated_payout=15000.00, is_approved=False
        ),
        CommissionCalculation(
            id=_id(), tenant_id=tenant, plan_id=plans[0].id, opportunity_id=opps[4].id,
            deal_value=220000.00, calculated_payout=22000.00, is_approved=False,
            paid_date=now - timedelta(days=5),
        ),
    ]
    for cc in calcs:
        db.add(cc)

    await db.commit()
    print(f"[SUCCESS] Seeded Sales database for {tenant}:")
    print(f"   - {len(teams)} teams, {len(reps)} reps")
    print(f"   - {len(accounts)} customer accounts, {len(contacts)} contacts")
    print(f"   - {len(opps)} opportunities across every funnel stage (incl. closed won/lost)")
    print(f"   - {len(leads)} inbound leads")
    print(f"   - {len(scores)} lead score indexes")
    print(f"   - {len(plans)} commission plans, {len(calcs)} commission calculations")
    return True


async def seed():
    # Ensure tables are built
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as db:
        await seed_tenant(db)

if __name__ == "__main__":
    asyncio.run(seed())
