"""
KAEOS Legal — Analytics Service
Contract portfolio composition, renewal exposure and clause risk, obligation
overdue rate, DSAR SLA risk and litigation exposure by stage - computed live
from tenant rows.
"""
from datetime import date, timedelta

from sqlalchemy import and_, case, func as sqlfunc, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.domain_analytics import DomainAnalytics
from app.legal.models.compliance import ComplianceObligation, ObligationStatus
from app.legal.models.contracts import Contract, ContractClause, ContractStatus
from app.legal.models.ip import IPStatus, Patent, Trademark
from app.legal.models.litigation import Case
from app.legal.models.privacy import DataSubjectRequest, DsarStatus

# A DSAR is "at risk" once its statutory deadline is within this window (or
# already past it) and it has not reached a terminal status.
_DSAR_RISK_WINDOW_DAYS = 7
_DSAR_TERMINAL = (DsarStatus.COMPLETED, DsarStatus.FAILED)


async def legal_analytics(db: AsyncSession, tenant_id: str, charts: bool = True) -> DomainAnalytics:
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

    # Obligation overdue rate — an obligation is overdue if it is not yet
    # satisfied (not COMPLETED/WAIVED) AND either its due_date has already
    # passed OR it was manually flagged OVERDUE. Deriving from due_date at read
    # time means a PENDING obligation whose deadline slipped is no longer
    # silently excluded (nothing sweeps the enum to OVERDUE). Null (never
    # 0/fake) when there are no obligations to rate at all, per the honesty
    # contract.
    overdue_obligation = and_(
        ComplianceObligation.status.notin_((ObligationStatus.COMPLETED, ObligationStatus.WAIVED)),
        or_(ComplianceObligation.status == ObligationStatus.OVERDUE,
            and_(ComplianceObligation.due_date.isnot(None),
                 ComplianceObligation.due_date < today)),
    )
    ob_q = await db.execute(
        select(sqlfunc.count(),
               sqlfunc.coalesce(sqlfunc.sum(case((overdue_obligation, 1), else_=0)), 0))
        .where(ComplianceObligation.tenant_id == tenant_id)
    )
    ob_total, ob_overdue = ob_q.one()
    ob_total, ob_overdue = int(ob_total or 0), int(ob_overdue or 0)
    overdue_rate = (ob_overdue / ob_total * 100.0) if ob_total else None

    # DSAR SLA risk — requests not yet terminal whose statutory deadline is
    # within the risk window (or already past it).
    dsar_q = await db.execute(
        select(sqlfunc.count())
        .where(DataSubjectRequest.tenant_id == tenant_id,
               DataSubjectRequest.status.notin_(_DSAR_TERMINAL),
               DataSubjectRequest.deadline_date <= today + timedelta(days=_DSAR_RISK_WINDOW_DAYS))
    )
    dsar_at_risk = int(dsar_q.scalar() or 0)

    # IP renewal exposure — registered marks / granted patents whose renewal or
    # expiry falls within 90 days (past-due included) and that are still legally
    # live (not ABANDONED/EXPIRED). Mirrors the contract-expiry pass so lapsing
    # trademarks and patents surface instead of only being echoed raw per-row.
    ip_cutoff = today + timedelta(days=90)
    _ip_terminal = (IPStatus.ABANDONED, IPStatus.EXPIRED)
    tm_due = int((await db.execute(
        select(sqlfunc.count()).where(
            Trademark.tenant_id == tenant_id,
            Trademark.status.notin_(_ip_terminal),
            Trademark.renewal_date.isnot(None),
            Trademark.renewal_date <= ip_cutoff)
    )).scalar() or 0)
    pat_due = int((await db.execute(
        select(sqlfunc.count()).where(
            Patent.tenant_id == tenant_id,
            Patent.status.notin_(_ip_terminal),
            Patent.expiry_date.isnot(None),
            Patent.expiry_date <= ip_cutoff)
    )).scalar() or 0)
    ip_renewals_due = tm_due + pat_due

    # Litigation exposure by stage — chart-only.
    exposure_by_stage: list[dict] = []
    if charts:
        stage_q = await db.execute(
            select(Case.stage, sqlfunc.coalesce(sqlfunc.sum(Case.exposure_amount), 0))
            .where(Case.tenant_id == tenant_id)
            .group_by(Case.stage)
        )
        exposure_by_stage = [
            {"label": (s.value if hasattr(s, "value") else str(s)), "value": float(v or 0)}
            for s, v in stage_q.all()
        ]
    total_exposure_q = await db.execute(
        select(sqlfunc.coalesce(sqlfunc.sum(Case.exposure_amount), 0))
        .where(Case.tenant_id == tenant_id)
    )
    total_litigation_exposure = float(total_exposure_q.scalar() or 0)

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
    if ob_overdue:
        insights.append({"severity": "critical",
                         "message": f"{ob_overdue} of {ob_total} compliance obligations are overdue."})
    if dsar_at_risk:
        insights.append({"severity": "warning",
                         "message": f"{dsar_at_risk} data subject request(s) are within {_DSAR_RISK_WINDOW_DAYS} days of their statutory deadline."})
    if ip_renewals_due:
        insights.append({"severity": "warning",
                         "message": f"{ip_renewals_due} trademark/patent renewal(s) fall due within 90 days."})
    if total_litigation_exposure:
        insights.append({"severity": "info",
                         "message": f"Total litigation exposure across open cases is ${total_litigation_exposure:,.0f}."})
    if not insights:
        insights.append({"severity": "info", "message": "Legal portfolio has no urgent exposure."})

    return {
        "domain": "legal",
        "kpis": [
            {"key": "active", "label": "Active Contracts", "value": active_count, "format": "number"},
            {"key": "active_value", "label": "Active Contract Value", "value": active_value, "format": "currency"},
            {"key": "in_review", "label": "In Review", "value": in_review, "format": "number"},
            {"key": "expiring", "label": "Expiring ≤90d", "value": int(expiring_count or 0), "format": "number"},
            {"key": "high_risk", "label": "High-Risk Clauses", "value": high_risk_clauses, "format": "number"},
            {"key": "avg_risk", "label": "Avg AI Risk Score", "value": float(avg_risk) if avg_risk is not None else None, "format": "number"},
            {"key": "obligation_overdue_rate", "label": "Obligation Overdue Rate", "value": overdue_rate, "format": "percent"},
            {"key": "dsar_at_risk", "label": "DSARs Near Deadline", "value": dsar_at_risk, "format": "number"},
            {"key": "ip_renewals_due", "label": "IP Renewals ≤90d", "value": ip_renewals_due, "format": "number"},
            {"key": "litigation_exposure", "label": "Litigation Exposure", "value": total_litigation_exposure, "format": "currency"},
        ],
        "charts": [
            {"key": "status_mix", "title": "Contracts by Status", "type": "donut",
             "items": [{"label": k, "value": v[0]} for k, v in by_status.items()]},
            {"key": "value_by_type", "title": "Contract Value by Type", "type": "bar", "items": value_by_type},
            {"key": "clause_risk", "title": "Clause Risk Levels", "type": "bar",
             "items": [{"label": k, "value": v} for k, v in clause_risk.items()]},
            {"key": "exposure_by_stage", "title": "Litigation Exposure by Stage", "type": "bar",
             "items": exposure_by_stage},
        ] if charts else [],
        "insights": insights,
    }
