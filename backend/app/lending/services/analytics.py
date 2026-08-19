"""
KAEOS Lending - Analytics Service

Real SQL aggregates over the tenant's loan book: application status mix,
approval rate, book value, and a fair-lending approval-rate ratio by protected
class (four-fifths). Returns the shared domain-analytics shape
(kpis/charts/insights). Honesty contract: a metric with no data to compute it
returns None + a note, never a fabricated 0.
"""
from __future__ import annotations

from collections import defaultdict

from sqlalchemy import func as sqlfunc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.domain_analytics import DomainAnalytics
from app.lending.models.core import LoanApplication, LoanStatus, UnderwritingDecision
from app.services.disparate_impact import four_fifths_test


async def lending_analytics(db: AsyncSession, tenant_id: str,
                            charts: bool = True) -> DomainAnalytics:
    # Status mix.
    status_q = await db.execute(
        select(LoanApplication.status, sqlfunc.count())
        .where(LoanApplication.tenant_id == tenant_id)
        .group_by(LoanApplication.status))
    status_counts = {s: int(c) for s, c in status_q.all()}
    total_apps = sum(status_counts.values())
    approved = status_counts.get(LoanStatus.APPROVED.value, 0)
    denied = status_counts.get(LoanStatus.DENIED.value, 0)
    decided = approved + denied

    # Approved book value.
    book_q = await db.execute(
        select(sqlfunc.coalesce(sqlfunc.sum(LoanApplication.amount), 0))
        .where(LoanApplication.tenant_id == tenant_id,
               LoanApplication.status == LoanStatus.APPROVED.value))
    book_value = float(book_q.scalar() or 0)

    # Honesty contract: approval rate is undefined with no decisions.
    approval_rate = round(approved / decided, 4) if decided else None
    approval_note = None if decided else "No underwriting decisions yet."

    # Annotated like charts_out/insights below: without it the heterogeneous
    # literals infer as list[object] and no longer satisfy DomainAnalytics.
    # REVIEW: this domain alone emits format "int"/"ratio" where the other nine
    # use "number"/"percent", and carries "note" on a non-null value. Preserved:
    # the frontend formats off these strings.
    kpis: list[dict] = [
        {"key": "total_applications", "label": "Applications", "value": total_apps,
         "format": "int"},
        {"key": "approval_rate", "label": "Approval Rate",
         "value": approval_rate, "format": "ratio", "note": approval_note},
        {"key": "approved_book_value", "label": "Approved Book Value",
         "value": book_value, "format": "currency"},
        {"key": "pending_hitl", "label": "Awaiting Review",
         "value": status_counts.get(LoanStatus.PENDING_HITL.value, 0), "format": "int"},
    ]

    charts_out: list[dict] = []
    insights: list[dict] = []

    if charts:
        charts_out.append({
            "key": "status_mix", "title": "Application Status", "type": "donut",
            "items": [{"label": k, "value": v} for k, v in sorted(status_counts.items())],
        })

        # Fair-lending: approval rate by protected class (four-fifths).
        fair = await fair_lending_ratios(db, tenant_id)
        if fair is None:
            insights.append({"severity": "info",
                             "message": "Fair-lending disparate-impact analysis needs "
                                        "decided applications with protected-class data; "
                                        "none available yet."})
        else:
            for attr, out in fair["attributes"].items():
                if out.get("status") == "ADVERSE_IMPACT":
                    insights.append({"severity": "critical",
                                     "message": f"Adverse impact detected on '{attr}' "
                                                "approval rates (below four-fifths)."})
                elif out.get("status") == "ADVISORY":
                    insights.append({"severity": "warning",
                                     "message": f"Possible disparity on '{attr}' approval "
                                                "rates (thin sample; not yet significant)."})
            charts_out.append({
                "key": "fair_lending", "title": "Fair-Lending Approval Ratio",
                "type": "bar",
                "items": [{"label": f"{attr}:{grp}",
                           "value": g.get("impact_ratio") or g.get("selection_rate")}
                          for attr, out in fair["attributes"].items()
                          for grp, g in (out.get("groups") or {}).items()],
            })

    return {"domain": "lending", "kpis": kpis, "charts": charts_out, "insights": insights}


async def fair_lending_ratios(db: AsyncSession, tenant_id: str):
    """Build four-fifths cohorts from real decided applications. Returns None
    when there is nothing to analyse (no protected-class data on decided apps)."""
    q = await db.execute(
        select(LoanApplication.protected_class, LoanApplication.status,
               UnderwritingDecision.decision)
        .join(UnderwritingDecision,
              UnderwritingDecision.application_id == LoanApplication.id)
        .where(LoanApplication.tenant_id == tenant_id,
               UnderwritingDecision.tenant_id == tenant_id))
    rows = q.all()

    cohorts: dict[str, dict[str, dict[str, int]]] = defaultdict(lambda: defaultdict(
        lambda: {"selected": 0, "total": 0}))
    any_data = False
    for protected, _status, decision in rows:
        if not isinstance(protected, dict):
            continue
        for attr, group in protected.items():
            if group in (None, ""):
                continue
            any_data = True
            cell = cohorts[attr][str(group)]
            cell["total"] += 1
            if decision == "APPROVE":
                cell["selected"] += 1

    if not any_data:
        return None
    return four_fifths_test({a: dict(g) for a, g in cohorts.items()})
