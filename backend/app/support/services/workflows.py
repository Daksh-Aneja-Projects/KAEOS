"""
KAEOS Support — Workflow Specs
Ticket lifecycle: new → assigned/open → pending-customer ↔ open → resolved →
closed, with reopen. Hooks stamp first-response and resolution timestamps so
SLA math stays truthful.
"""
from app.core.workflow import WorkflowSpec, TransitionContext
from app.support.models.tickets import Ticket


def _first_response(t: Ticket, ctx: TransitionContext) -> None:
    if t.first_response_at is None:
        t.first_response_at = ctx.now


def _resolved(t: Ticket, ctx: TransitionContext) -> None:
    _first_response(t, ctx)
    t.resolved_at = ctx.now


def _reopened(t: Ticket, ctx: TransitionContext) -> None:
    t.resolved_at = None


TICKET_WORKFLOW = WorkflowSpec(
    domain="support",
    entity_type="ticket",
    model=Ticket,
    transitions={
        "NEW": ["ASSIGNED", "OPEN", "CLOSED"],
        "ASSIGNED": ["OPEN", "PENDING_CUSTOMER", "RESOLVED"],
        "OPEN": ["PENDING_CUSTOMER", "RESOLVED"],
        "PENDING_CUSTOMER": ["OPEN", "RESOLVED", "CLOSED"],
        "RESOLVED": ["CLOSED", "OPEN"],
    },
    on_enter={
        "ASSIGNED": _first_response,
        "OPEN": _reopened,
        "RESOLVED": _resolved,
    },
    sla_hours={"NEW": 4, "ASSIGNED": 24, "OPEN": 48, "PENDING_CUSTOMER": 120},
)

SPECS = {"ticket": TICKET_WORKFLOW}
