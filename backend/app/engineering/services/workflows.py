"""
KAEOS Engineering — Workflow Specs
Incident lifecycle (with MTTA/MTTR stamping) and deployment promotion.
"""
from datetime import timezone

from app.core.workflow import WorkflowSpec, TransitionContext
from app.engineering.models.delivery import Deployment
from app.engineering.models.incidents import Incident


def _mins_since(start, now) -> int:
    if start is None:
        return 0
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    return max(int((now - start).total_seconds() // 60), 0)


def _triaged(inc: Incident, ctx: TransitionContext) -> None:
    if inc.acknowledged_at is None:
        inc.acknowledged_at = ctx.now
        inc.time_to_acknowledge_mins = _mins_since(inc.detected_at, ctx.now)


def _resolved(inc: Incident, ctx: TransitionContext) -> None:
    _triaged(inc, ctx)
    inc.resolved_at = ctx.now
    inc.time_to_resolve_mins = _mins_since(inc.detected_at, ctx.now)


INCIDENT_WORKFLOW = WorkflowSpec(
    domain="engineering",
    entity_type="incident",
    model=Incident,
    transitions={
        "DETECTED": ["TRIAGED"],
        "TRIAGED": ["MITIGATING", "RESOLVED"],
        "MITIGATING": ["MONITORING", "RESOLVED"],
        "MONITORING": ["RESOLVED", "MITIGATING"],
        "RESOLVED": ["POSTMORTEM_DUE", "CLOSED"],
        "POSTMORTEM_DUE": ["CLOSED"],
    },
    on_enter={"TRIAGED": _triaged, "RESOLVED": _resolved},
)

DEPLOYMENT_WORKFLOW = WorkflowSpec(
    domain="engineering",
    entity_type="deployment",
    model=Deployment,
    transitions={
        "PENDING_APPROVAL": ["IN_PROGRESS"],
        "IN_PROGRESS": ["SUCCEEDED", "FAILED"],
        "FAILED": ["ROLLED_BACK"],
        "SUCCEEDED": ["ROLLED_BACK"],
    },
)

SPECS = {
    "incident": INCIDENT_WORKFLOW,
    "deployment": DEPLOYMENT_WORKFLOW,
}
