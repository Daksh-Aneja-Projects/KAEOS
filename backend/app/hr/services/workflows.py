"""
KAEOS HR — Workflow Specs
State machines for time-off requests, job requisitions and candidate stages.
"""
from app.core.workflow import WorkflowSpec, TransitionContext
from app.hr.models.recruiting import JobRequisition
from app.hr.models.time_attendance import TimeOffRequest


def _timeoff_approved(req: TimeOffRequest, ctx: TransitionContext) -> None:
    req.ai_auto_approved = False  # a human transition always overrides auto-approval
    if ctx.note:
        req.ai_decision_reason = ctx.note[:256]


TIME_OFF_WORKFLOW = WorkflowSpec(
    domain="hr",
    entity_type="time_off_request",
    model=TimeOffRequest,
    transitions={
        "REQUESTED": ["APPROVED", "DENIED", "CANCELLED"],
        "APPROVED": ["CANCELLED"],
        "DENIED": ["REQUESTED"],
    },
    on_enter={"APPROVED": _timeoff_approved},
)

REQUISITION_WORKFLOW = WorkflowSpec(
    domain="hr",
    entity_type="job_requisition",
    model=JobRequisition,
    transitions={
        "DRAFT": ["PENDING_APPROVAL", "CANCELLED"],
        "PENDING_APPROVAL": ["OPEN", "DRAFT", "CANCELLED"],
        "OPEN": ["ON_HOLD", "FILLED", "CANCELLED"],
        "ON_HOLD": ["OPEN", "CANCELLED"],
    },
)

# NOTE: candidate stage advancement intentionally has NO WorkflowSpec here —
# POST /hr/candidates/{id}/advance (gated, with screening provenance) is the
# single sanctioned path; a second engine-driven path would fork the funnel.

SPECS = {
    "time_off_request": TIME_OFF_WORKFLOW,
    "job_requisition": REQUISITION_WORKFLOW,
}
