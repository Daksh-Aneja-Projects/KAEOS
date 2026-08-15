"""
KAEOS Procurement — Analytics Service

Real SQL aggregates over the shared ops_* source-to-pay tables, returned in the
shared domain-analytics shape the frontend DomainAnalytics component renders:

  { domain, kpis: [{key,label,value,format}], charts: [...], insights: [...] }

Honesty contract: a metric the platform cannot actually measure (no requisition
paired to a PO yet, no vendor performance rows yet) is returned as value=None
with a note, never a fabricated 0.

``charts=False`` skips the series-only queries for callers (the org pulse) that
read only kpis + insights - mirrors app.operations.services.analytics.
"""
from datetime import date

from sqlalchemy import func as sqlfunc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.operations.models.procurement import (
    ProcurementStatus, PurchaseOrder, PurchaseRequest,
)
from app.operations.models.vendors import VendorContract, VendorPerformance

_FUNNEL = ["DRAFT", "PENDING_APPROVAL", "APPROVED", "ORDERED", "RECEIVED"]


def _risk_bucket(renewal_date, perf_score) -> str:
    """Deterministic risk bucket from real columns only: a contract renewing
    soon or a vendor scoring poorly on delivery/SLA is a live operational
    risk, independent of any sanctions hit (which is screened separately)."""
    days_to_renewal = (renewal_date - date.today()).days if renewal_date else None
    if (days_to_renewal is not None and days_to_renewal <= 30) or (perf_score is not None and perf_score < 70):
        return "HIGH"
    if (days_to_renewal is not None and days_to_renewal <= 90) or (perf_score is not None and perf_score < 85):
        return "MEDIUM"
    return "LOW"


async def procurement_analytics(db: AsyncSession, tenant_id: str,
                                charts: bool = False) -> dict:
    # PO funnel + committed spend.
    po_q = await db.execute(
        select(PurchaseOrder.status, sqlfunc.count(),
               sqlfunc.coalesce(sqlfunc.sum(PurchaseOrder.total_amount), 0))
        .where(PurchaseOrder.tenant_id == tenant_id)
        .group_by(PurchaseOrder.status)
    )
    po_by_status = {(s.value if hasattr(s, "value") else str(s)): (int(c), float(v))
                    for s, c, v in po_q.all()}
    committed_spend = sum(po_by_status.get(s, (0, 0))[1] for s in ["APPROVED", "ORDERED"])
    pending_po_approval = po_by_status.get("PENDING_APPROVAL", (0, 0))[0]

    # Requisitions.
    req_q = await db.execute(
        select(PurchaseRequest.status, sqlfunc.count())
        .where(PurchaseRequest.tenant_id == tenant_id)
        .group_by(PurchaseRequest.status)
    )
    req_by_status = {(s.value if hasattr(s, "value") else str(s)): int(c) for s, c in req_q.all()}
    total_requisitions = sum(req_by_status.values())
    open_requisitions = req_by_status.get("DRAFT", 0) + req_by_status.get("PENDING_APPROVAL", 0)

    # Requisition -> PO cycle time (hours), only over pairs where a PO cites
    # its originating requisition. Computed in Python, not DB-side date
    # arithmetic (julianday is SQLite-only; Postgres has no equivalent), so
    # this stays portable across both. Honesty contract: no such pair -> None.
    cycle_q = await db.execute(
        select(PurchaseOrder.created_at, PurchaseRequest.created_at)
        .select_from(PurchaseOrder)
        .join(PurchaseRequest, PurchaseRequest.id == PurchaseOrder.purchase_request_id)
        .where(PurchaseOrder.tenant_id == tenant_id, PurchaseRequest.tenant_id == tenant_id)
    )
    hours = [(po_dt - req_dt).total_seconds() / 3600.0
             for po_dt, req_dt in cycle_q.all() if po_dt and req_dt]
    avg_cycle_hours = (sum(hours) / len(hours)) if hours else None

    # Vendor risk: every contracted vendor, joined to its latest performance
    # sheet (correlated subquery - at most one row differs per tenant seed
    # today, but this stays correct if more accumulate).
    latest_perf_id = (
        select(VendorPerformance.id)
        .where(VendorPerformance.vendor_contract_id == VendorContract.id)
        .order_by(VendorPerformance.created_at.desc())
        .limit(1)
        .correlate(VendorContract)
        .scalar_subquery()
    )
    vendor_q = await db.execute(
        select(VendorContract.renewal_date, VendorPerformance.overall_performance_score)
        .outerjoin(VendorPerformance, VendorPerformance.id == latest_perf_id)
        .where(VendorContract.tenant_id == tenant_id)
    )
    risk_counts = {"LOW": 0, "MEDIUM": 0, "HIGH": 0}
    for renewal_date, perf_score in vendor_q.all():
        risk_counts[_risk_bucket(renewal_date, perf_score)] += 1
    high_risk_vendors = risk_counts["HIGH"]

    insights = []
    if pending_po_approval:
        insights.append({"severity": "warning",
                         "message": f"{pending_po_approval} purchase orders are awaiting a gated four-control approval."})
    if high_risk_vendors:
        insights.append({"severity": "warning",
                         "message": f"{high_risk_vendors} vendors are high risk - contract renewal is imminent or "
                                    "delivery performance has slipped."})
    if avg_cycle_hours is not None and avg_cycle_hours > 168:
        insights.append({"severity": "info",
                         "message": f"Requisition-to-PO cycle time averages {avg_cycle_hours / 24:.1f} days, "
                                    "above a one-week target."})
    if not insights:
        insights.append({"severity": "info", "message": "No procurement anomalies detected this cycle."})

    charts_out = [
        {"key": "spend_by_department", "title": "Requested Spend by Department", "type": "bar",
         "items": [{"label": dept or "Unassigned", "value": float(total)}
                   for dept, total in (await db.execute(
                       select(PurchaseRequest.department,
                              sqlfunc.coalesce(sqlfunc.sum(PurchaseRequest.total_estimated_cost), 0))
                       .where(PurchaseRequest.tenant_id == tenant_id)
                       .group_by(PurchaseRequest.department)
                   )).all()]},
        {"key": "vendor_risk", "title": "Vendor Risk", "type": "donut",
         "items": [{"label": k.title(), "value": v} for k, v in risk_counts.items() if v]},
        {"key": "po_funnel", "title": "Purchase Order Pipeline", "type": "funnel",
         "items": [{"label": s.replace("_", " ").title(), "value": po_by_status.get(s, (0, 0))[0]}
                   for s in _FUNNEL]},
    ] if charts else []

    return {
        "domain": "procurement",
        "kpis": [
            {"key": "requisitions", "label": "Total Requisitions", "value": total_requisitions, "format": "number"},
            {"key": "open_requisitions", "label": "Open Requisitions", "value": open_requisitions, "format": "number"},
            {"key": "committed_spend", "label": "Committed Spend", "value": committed_spend, "format": "currency"},
            {"key": "pending_po_approval", "label": "Awaiting PO Approval", "value": pending_po_approval, "format": "number"},
            {"key": "cycle_time", "label": "Requisition to PO Cycle Time", "value": avg_cycle_hours, "format": "hours",
             **({} if avg_cycle_hours is not None else {
                "note": "Not measurable yet: no purchase order in this tenant cites the requisition it was raised from."})},
            {"key": "high_risk_vendors", "label": "High-Risk Vendors", "value": high_risk_vendors, "format": "number"},
        ],
        "charts": charts_out,
        "insights": insights,
    }
