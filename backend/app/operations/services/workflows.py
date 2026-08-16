"""
KAEOS Operations — Workflow Specs
Procure-to-pay chain: purchase requests and purchase orders share the
ProcurementStatus enum but have distinct legal transition maps. Facility work
orders run their own OPEN -> IN_PROGRESS -> RESOLVED -> CLOSED lifecycle.
"""
from app.core.workflow import WorkflowSpec
from app.operations.models.facilities import WorkOrder
from app.operations.models.procurement import PurchaseOrder, PurchaseRequest

PURCHASE_REQUEST_WORKFLOW = WorkflowSpec(
    domain="operations",
    entity_type="purchase_request",
    model=PurchaseRequest,
    transitions={
        "DRAFT": ["PENDING_APPROVAL", "CANCELLED"],
        "PENDING_APPROVAL": ["APPROVED", "DRAFT", "CANCELLED"],
        "APPROVED": ["ORDERED", "CANCELLED"],
        "ORDERED": ["RECEIVED", "CANCELLED"],
    },
    sla_hours={"PENDING_APPROVAL": 48, "APPROVED": 120, "ORDERED": 336},
)

PURCHASE_ORDER_WORKFLOW = WorkflowSpec(
    domain="operations",
    entity_type="purchase_order",
    model=PurchaseOrder,
    transitions={
        "DRAFT": ["PENDING_APPROVAL", "CANCELLED"],
        "PENDING_APPROVAL": ["APPROVED", "CANCELLED"],
        "APPROVED": ["ORDERED", "CANCELLED"],
        "ORDERED": ["RECEIVED"],
    },
    sla_hours={"PENDING_APPROVAL": 48, "ORDERED": 336},
)

def _stamp_resolved(wo, ctx) -> None:
    """On entering RESOLVED, record when the work order was actually resolved."""
    wo.resolved_at = ctx.now


WORK_ORDER_WORKFLOW = WorkflowSpec(
    domain="operations",
    entity_type="work_order",
    model=WorkOrder,
    transitions={
        "OPEN": ["IN_PROGRESS", "RESOLVED"],
        "IN_PROGRESS": ["RESOLVED"],
        "RESOLVED": ["CLOSED"],
    },
    on_enter={"RESOLVED": _stamp_resolved},
)

SPECS = {
    "purchase_request": PURCHASE_REQUEST_WORKFLOW,
    "purchase_order": PURCHASE_ORDER_WORKFLOW,
    "work_order": WORK_ORDER_WORKFLOW,
}


if __name__ == "__main__":  # tiny self-check: the work-order lifecycle is wired
    from types import SimpleNamespace
    from datetime import datetime, timezone
    assert WORK_ORDER_WORKFLOW.allowed_from("OPEN") == ["IN_PROGRESS", "RESOLVED"]
    assert WORK_ORDER_WORKFLOW.allowed_from("RESOLVED") == ["CLOSED"]
    assert "CLOSED" not in WORK_ORDER_WORKFLOW.allowed_from("OPEN")  # no skip-to-closed
    _wo = SimpleNamespace(resolved_at=None)
    WORK_ORDER_WORKFLOW.on_enter["RESOLVED"](_wo, SimpleNamespace(now=datetime.now(timezone.utc)))
    assert _wo.resolved_at is not None, "RESOLVED hook must stamp resolved_at"
    print("operations work_order workflow OK")
