"""
KAEOS Operations — Analytics Service
Procurement funnel, committed spend, goods-receipt quality and resource
utilization, computed live from tenant rows.
"""
from sqlalchemy import case, func as sqlfunc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.operations.models.procurement import (
    GoodsReceipt, ProcurementStatus, PurchaseOrder, PurchaseRequest,
)
from app.operations.models.resources import Resource, ResourceAllocation

_FUNNEL = ["DRAFT", "PENDING_APPROVAL", "APPROVED", "ORDERED", "RECEIVED"]


async def operations_analytics(db: AsyncSession, tenant_id: str) -> dict:
    po_q = await db.execute(
        select(PurchaseOrder.status, sqlfunc.count(),
               sqlfunc.coalesce(sqlfunc.sum(PurchaseOrder.total_amount), 0))
        .where(PurchaseOrder.tenant_id == tenant_id)
        .group_by(PurchaseOrder.status)
    )
    po_by_status = {(s.value if hasattr(s, "value") else str(s)): (int(c), float(v))
                    for s, c, v in po_q.all()}

    funnel = [{"label": s.replace("_", " ").title(), "value": po_by_status.get(s, (0, 0))[0]}
              for s in _FUNNEL]

    committed = sum(po_by_status.get(s, (0, 0))[1] for s in ["APPROVED", "ORDERED"])
    open_pos = sum(po_by_status.get(s, (0, 0))[0] for s in ["PENDING_APPROVAL", "APPROVED", "ORDERED"])

    pr_q = await db.execute(
        select(sqlfunc.count())
        .where(PurchaseRequest.tenant_id == tenant_id,
               PurchaseRequest.status == ProcurementStatus.PENDING_APPROVAL)
    )
    pending_requests = int(pr_q.scalar() or 0)

    gr_q = await db.execute(
        select(sqlfunc.count(),
               sqlfunc.coalesce(sqlfunc.sum(case((GoodsReceipt.is_damaged == True, 1), else_=0)), 0))  # noqa: E712
        .where(GoodsReceipt.tenant_id == tenant_id)
    )
    gr_total, gr_damaged = gr_q.one()
    gr_total = int(gr_total or 0)
    gr_damaged = int(gr_damaged or 0)
    damage_rate = (gr_damaged / gr_total * 100) if gr_total else None

    util_q = await db.execute(
        select(sqlfunc.avg(ResourceAllocation.utilization_percentage))
        .where(ResourceAllocation.tenant_id == tenant_id)
    )
    avg_utilization = util_q.scalar()

    res_q = await db.execute(
        select(Resource.resource_type, sqlfunc.count())
        .where(Resource.tenant_id == tenant_id)
        .group_by(Resource.resource_type)
    )
    resources_by_type = [{"label": t, "value": int(c)} for t, c in res_q.all()]

    insights = []
    if pending_requests:
        insights.append({"severity": "warning",
                         "message": f"{pending_requests} purchase requests are waiting for approval."})
    if damage_rate is not None and damage_rate > 5:
        insights.append({"severity": "critical",
                         "message": f"Goods damage rate is {damage_rate:.1f}% — above the 5% threshold."})
    if avg_utilization is not None and float(avg_utilization) > 90:
        insights.append({"severity": "warning",
                         "message": f"Average resource utilization is {float(avg_utilization):.0f}% — capacity is tight."})
    if not insights:
        insights.append({"severity": "info", "message": "Operations pipeline is running clean."})

    return {
        "domain": "operations",
        "kpis": [
            {"key": "committed", "label": "Committed Spend", "value": committed, "format": "currency"},
            {"key": "open_pos", "label": "Open POs", "value": open_pos, "format": "number"},
            {"key": "pending_prs", "label": "Pending Requests", "value": pending_requests, "format": "number"},
            {"key": "damage", "label": "Goods Damage Rate", "value": damage_rate, "format": "percent"},
            {"key": "utilization", "label": "Avg Utilization", "value": float(avg_utilization) if avg_utilization is not None else None, "format": "percent"},
            {"key": "receipts", "label": "Goods Receipts", "value": gr_total, "format": "number"},
        ],
        "charts": [
            {"key": "po_funnel", "title": "PO Pipeline", "type": "funnel", "items": funnel},
            {"key": "resources", "title": "Resources by Type", "type": "donut", "items": resources_by_type},
        ],
        "insights": insights,
    }
