"""
KAEOS Operations — Workflow Specs
Procure-to-pay chain: purchase requests and purchase orders share the
ProcurementStatus enum but have distinct legal transition maps.
"""
from app.core.workflow import WorkflowSpec
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
)

SPECS = {
    "purchase_request": PURCHASE_REQUEST_WORKFLOW,
    "purchase_order": PURCHASE_ORDER_WORKFLOW,
}
