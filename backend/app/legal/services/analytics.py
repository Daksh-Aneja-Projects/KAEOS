"""
KAEOS Legal — Analytics Service
Contract portfolio composition, renewal exposure and clause risk, computed
live from tenant rows.
"""
from datetime import date, timedelta

from sqlalchemy import and_, case, func as sqlfunc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.legal.models.contracts import Contract, ContractClause, ContractStatus


async def legal_analytics(db: AsyncSession, tenant_id: str, charts: bool = True) -> dict:
    """`charts=False` skips the series queries that feed no KPI and no insight,
    for callers (the org pulse) that only read kpis + insights."""
    today = date.today()

    status_q = await db.execute(
        select(Contract.status, sqlfunc.count(),
               sqlfunc.coalesce(sqlfunc.sum(Contract.contract_value), 0))
        .where(Contract.tenant_id == tenant_id)
        .group_by(Contract.status)
    )
    by_status = {(s.value if hasattr(s, "value") else str(s)): (int(c), float(v))
                 for s, c, v in status_q.all()}

    # Contract value by type — chart-only.
    value_by_type: list[dict] = []
    if charts:
        type_q = await db.execute(
            select(Contract.contract_type, sqlfunc.coalesce(sqlfunc.sum(Contract.contract_value), 0))
            .where(Contract.tenant_id == tenant_id)
            .group_by(Contract.contract_type)
            .order_by(sqlfunc.sum(Contract.contract_value).desc())
            .limit(6)
        )
        value_by_type = [{"label": t, "value": float(v or 0)} for t, v in type_q.all()]

    active_count, active_value = by_status.get("ACTIVE", (0, 0))
    in_review = by_status.get("IN_REVIEW", (0, 0))[0]

    # Renewal exposure and the portfolio risk average are both aggregates over
    # the tenant's contracts, so one pass answers both. AVG already ignores
    # NULL scores, which is what the old `ai_risk_score IS NOT NULL` filter did.
    expiring = and_(Contract.status == ContractStatus.ACTIVE,
                    Contract.expiry_date.isnot(None),
                    Contract.expiry_date <= today + timedelta(days=90))
    exposure_q = await db.execute(
        select(sqlfunc.coalesce(sqlfunc.sum(case((expiring, 1), else_=0)), 0),
               sqlfunc.coalesce(sqlfunc.sum(case((expiring, Contract.contract_value), else_=0)), 0),
               sqlfunc.avg(Contract.ai_risk_score))
        .where(Contract.tenant_id == tenant_id)
    )
    expiring_count, expiring_value, avg_risk = exposure_q.one()

    risk_q = await db.execute(
        select(ContractClause.risk_level, sqlfunc.count())
        .where(ContractClause.tenant_id == tenant_id)
        .group_by(ContractClause.risk_level)
    )
    clause_risk = {(r.value if hasattr(r, "value") else str(r)): int(c) for r, c in risk_q.all()}
    high_risk_clauses = clause_risk.get("HIGH", 0)

    insights = []
    if expiring_count:
        insights.append({"severity": "warning",
                         "message": f"{int(expiring_count)} active contracts (${float(expiring_value or 0):,.0f}) expire within 90 days."})
    if high_risk_clauses:
        insights.append({"severity": "critical",
                         "message": f"{high_risk_clauses} HIGH-risk clauses need counsel review."})
    if in_review:
        insights.append({"severity": "info",
                         "message": f"{in_review} contracts are sitting in legal review."})
    if not insights:
        insights.append({"severity": "info", "message": "Contract portfolio has no urgent exposure."})

    return {
        "domain": "legal",
        "kpis": [
            {"key": "active", "label": "Active Contracts", "value": active_count, "format": "number"},
            {"key": "active_value", "label": "Active Contract Value", "value": active_value, "format": "currency"},
            {"key": "in_review", "label": "In Review", "value": in_review, "format": "number"},
            {"key": "expiring", "label": "Expiring ≤90d", "value": int(expiring_count or 0), "format": "number"},
            {"key": "high_risk", "label": "High-Risk Clauses", "value": high_risk_clauses, "format": "number"},
            {"key": "avg_risk", "label": "Avg AI Risk Score", "value": float(avg_risk) if avg_risk is not None else None, "format": "number"},
        ],
        "charts": [
            {"key": "status_mix", "title": "Contracts by Status", "type": "donut",
             "items": [{"label": k, "value": v[0]} for k, v in by_status.items()]},
            {"key": "value_by_type", "title": "Contract Value by Type", "type": "bar", "items": value_by_type},
            {"key": "clause_risk", "title": "Clause Risk Levels", "type": "bar",
             "items": [{"label": k, "value": v} for k, v in clause_risk.items()]},
        ] if charts else [],
        "insights": insights,
    }
