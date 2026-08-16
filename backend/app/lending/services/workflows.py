"""
KAEOS Lending - Workflow Specs

Declarative state machines for the loan-application lifecycle and the
serviced-loan delinquency states; every transition flows through
app.core.workflow.apply_transition. The underwriting DECISION itself (moving
an application to APPROVED / DENIED / PENDING_HITL) is deliberately NOT
reachable through the generic engine - it must go through
UnderwriterAgent.underwrite, which runs the real fail-closed ECOA /
FAIR_LENDING / TILA gates before it may set that state. A generic transition
to those states would bypass every one of those controls, the same reason
finance's INVOICE_WORKFLOW has no manual PAID transition.
"""
from app.core.workflow import TransitionContext, WorkflowSpec
from app.lending.models.core import LoanApplication
from app.lending.models.servicing import ServicedLoan


def _application_withdrawn(app: LoanApplication, ctx: TransitionContext) -> None:
    # The status write is the whole effect; nothing else to derive.
    pass


APPLICATION_WORKFLOW = WorkflowSpec(
    domain="lending",
    entity_type="loan_application",
    model=LoanApplication,
    transitions={
        "RECEIVED": ["WITHDRAWN"],
        "IN_REVIEW": ["WITHDRAWN"],
        "PENDING_HITL": ["WITHDRAWN"],
    },
    on_enter={"WITHDRAWN": _application_withdrawn},
    sla_hours={"IN_REVIEW": 48, "PENDING_HITL": 24},
)


# These hooks are synchronous and receive no DB session (see TransitionHook),
# so they cannot resolve the loan's open CollectionCase(s) here - querying via
# the ORM object's sync session inside the async request is the MissingGreenlet
# trap. The collections-case closure lives in the router's transition endpoint.
def _loan_paid_off(loan: ServicedLoan, ctx: TransitionContext) -> None:
    loan.outstanding_principal = 0
    loan.days_past_due = 0


def _loan_cured(loan: ServicedLoan, ctx: TransitionContext) -> None:
    loan.days_past_due = 0


SERVICED_LOAN_WORKFLOW = WorkflowSpec(
    domain="lending",
    entity_type="serviced_loan",
    model=ServicedLoan,
    transitions={
        "CURRENT": ["DELINQUENT", "PAID_OFF"],
        "DELINQUENT": ["CURRENT", "DEFAULT", "PAID_OFF"],
        "DEFAULT": ["CURRENT"],
    },
    on_enter={"PAID_OFF": _loan_paid_off, "CURRENT": _loan_cured},
    role_requirements={"DEFAULT": "admin"},
    sla_hours={"DELINQUENT": 720},  # 30 days without resolution flags for review
)

SPECS = {
    "loan_application": APPLICATION_WORKFLOW,
    "serviced_loan": SERVICED_LOAN_WORKFLOW,
}
