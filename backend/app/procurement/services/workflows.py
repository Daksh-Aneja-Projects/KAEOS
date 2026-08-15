"""
KAEOS Procurement — Workflow Specs

Declarative lifecycle for requisitions and purchase orders, routed through the
shared app.core.workflow engine (apply_transition) rather than a hand-rolled
status write, so every move is validated, role-gated, and appended to the
cross-domain workflow-event audit trail.

Entity-type strings are prefixed ``procurement_`` because
app.services.workflow_registry merges every domain's SPECS dict into one
entity_type-keyed map and entity_type strings must be globally unique - the
bare "purchase_request" / "purchase_order" keys already belong to Operations
(app.operations.services.workflows), which governs the SAME underlying
ops_purchase_requests / ops_purchase_orders rows for its own procurement tab.

PENDING_APPROVAL -> APPROVED is deliberately ABSENT from the purchase-order
transition map. That move is a real financial control point (spend authority,
segregation of duties, three-way match, OFAC), and it is fail-closed via
POST /procurement/purchase-orders/{id}/approve (app.procurement.services.
source_to_pay.approve_purchase_order), which runs the four control gates
before the state changes. A bare workflow transition would flip the status
with no controls at all - exactly the bypass this file must not open.
"""
from app.core.workflow import WorkflowSpec
from app.operations.models.procurement import PurchaseOrder, PurchaseRequest

REQUISITION_WORKFLOW = WorkflowSpec(
    domain="procurement",
    entity_type="procurement_requisition",
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
    domain="procurement",
    entity_type="procurement_purchase_order",
    model=PurchaseOrder,
    transitions={
        "DRAFT": ["PENDING_APPROVAL", "CANCELLED"],
        "PENDING_APPROVAL": ["CANCELLED"],  # see module docstring: approval is gated, not a bare transition
        "APPROVED": ["ORDERED", "CANCELLED"],
        "ORDERED": ["RECEIVED", "CANCELLED"],
    },
    sla_hours={"PENDING_APPROVAL": 48, "ORDERED": 336},
)

SPECS = {
    "procurement_requisition": REQUISITION_WORKFLOW,
    "procurement_purchase_order": PURCHASE_ORDER_WORKFLOW,
}
