"""
KAEOS Sales — Workflow Specs
Opportunity stage machine: strictly forward through the pipeline, with a
close-lost exit from every live stage.
"""
from app.core.workflow import WorkflowSpec, TransitionContext
from app.sales.models.pipeline import Opportunity


def _won(opp: Opportunity, ctx: TransitionContext) -> None:
    opp.probability = 100.0


def _lost(opp: Opportunity, ctx: TransitionContext) -> None:
    opp.probability = 0.0
    if ctx.note:
        opp.ai_next_step = f"Closed lost: {ctx.note}"[:512]


OPPORTUNITY_WORKFLOW = WorkflowSpec(
    domain="sales",
    entity_type="opportunity",
    model=Opportunity,
    status_attr="stage",
    transitions={
        "PROSPECTING": ["QUALIFICATION", "CLOSED_LOST"],
        "QUALIFICATION": ["PROPOSAL", "CLOSED_LOST"],
        "PROPOSAL": ["NEGOTIATION", "CLOSED_LOST"],
        "NEGOTIATION": ["CLOSED_WON", "CLOSED_LOST"],
    },
    on_enter={"CLOSED_WON": _won, "CLOSED_LOST": _lost},
)

SPECS = {"opportunity": OPPORTUNITY_WORKFLOW}
