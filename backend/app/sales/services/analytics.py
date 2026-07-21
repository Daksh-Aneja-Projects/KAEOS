"""
KAEOS Sales — Analytics Service
Pipeline funnel (count + value), weighted pipeline, win rate, average deal
size and top accounts by ARR, computed live from tenant rows.
"""
from sqlalchemy import func as sqlfunc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.sales.models.accounts import Account
from app.sales.models.pipeline import Opportunity, OpportunityStage

_STAGE_ORDER = ["PROSPECTING", "QUALIFICATION", "PROPOSAL", "NEGOTIATION",
                "CLOSED_WON", "CLOSED_LOST"]
_OPEN_STAGES = [OpportunityStage.PROSPECTING, OpportunityStage.QUALIFICATION,
                OpportunityStage.PROPOSAL, OpportunityStage.NEGOTIATION]


async def sales_analytics(db: AsyncSession, tenant_id: str) -> dict:
    stage_q = await db.execute(
        select(Opportunity.stage, sqlfunc.count(),
               sqlfunc.coalesce(sqlfunc.sum(Opportunity.amount), 0))
        .where(Opportunity.tenant_id == tenant_id)
        .group_by(Opportunity.stage)
    )
    by_stage = {(s.value if hasattr(s, "value") else str(s)): (int(c), float(v))
                for s, c, v in stage_q.all()}

    funnel_counts = [{"label": s.replace("_", " ").title(), "value": by_stage.get(s, (0, 0))[0]}
                     for s in _STAGE_ORDER[:4]]
    funnel_value = [{"label": s.replace("_", " ").title(), "value": by_stage.get(s, (0, 0))[1]}
                    for s in _STAGE_ORDER[:4]]

    won_count, won_value = by_stage.get("CLOSED_WON", (0, 0))
    lost_count, _ = by_stage.get("CLOSED_LOST", (0, 0))
    closed = won_count + lost_count
    win_rate = (won_count / closed * 100) if closed else None
    avg_deal = (won_value / won_count) if won_count else None

    open_pipeline = sum(by_stage.get(s, (0, 0))[1] for s in _STAGE_ORDER[:4])
    open_count = sum(by_stage.get(s, (0, 0))[0] for s in _STAGE_ORDER[:4])

    # Probability-weighted pipeline over open deals.
    weighted_q = await db.execute(
        select(sqlfunc.coalesce(
            sqlfunc.sum(Opportunity.amount * Opportunity.probability / 100.0), 0))
        .where(Opportunity.tenant_id == tenant_id,
               Opportunity.stage.in_(_OPEN_STAGES))
    )
    weighted_pipeline = float(weighted_q.scalar() or 0)

    stalled_q = await db.execute(
        select(sqlfunc.count())
        .where(Opportunity.tenant_id == tenant_id,
               Opportunity.stage.in_(_OPEN_STAGES),
               Opportunity.ai_stalled_flag.isnot(None))
    )
    stalled = int(stalled_q.scalar() or 0)

    acct_q = await db.execute(
        select(Account.name, Account.annual_recurring_revenue)
        .where(Account.tenant_id == tenant_id)
        .order_by(Account.annual_recurring_revenue.desc())
        .limit(5)
    )
    top_accounts = [{"label": n, "value": float(v or 0)} for n, v in acct_q.all()]

    insights = []
    if stalled:
        insights.append({"severity": "warning",
                         "message": f"{stalled} open opportunities are flagged as stalled — nudge the owners."})
    if win_rate is not None and win_rate < 25 and closed >= 4:
        insights.append({"severity": "warning",
                         "message": f"Win rate is {win_rate:.0f}% — below the 25% healthy floor."})
    neg_count = by_stage.get("NEGOTIATION", (0, 0))[0]
    if open_count and neg_count == 0:
        insights.append({"severity": "info",
                         "message": "No deals in negotiation — late-stage pipeline is empty."})
    if not insights:
        insights.append({"severity": "info", "message": "Pipeline health is nominal."})

    return {
        "domain": "sales",
        "kpis": [
            {"key": "pipeline", "label": "Open Pipeline", "value": open_pipeline, "format": "currency"},
            {"key": "weighted", "label": "Weighted Pipeline", "value": weighted_pipeline, "format": "currency"},
            {"key": "open_deals", "label": "Open Deals", "value": open_count, "format": "number"},
            {"key": "win_rate", "label": "Win Rate", "value": win_rate, "format": "percent"},
            {"key": "avg_deal", "label": "Avg Won Deal", "value": avg_deal, "format": "currency"},
            {"key": "won_ytd", "label": "Closed Won Value", "value": won_value, "format": "currency"},
        ],
        "charts": [
            {"key": "funnel_count", "title": "Pipeline Funnel (deals)", "type": "funnel", "items": funnel_counts},
            {"key": "funnel_value", "title": "Pipeline Funnel (value $)", "type": "bar", "items": funnel_value},
            {"key": "top_accounts", "title": "Top Accounts by ARR", "type": "bar", "items": top_accounts},
        ],
        "insights": insights,
    }
