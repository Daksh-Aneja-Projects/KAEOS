"""
KAEOS Legal — Workflow Specs
Contract lifecycle: draft → review → approved → signed → active → expired /
terminated. Activation stamps the effective date when counsel left it blank.
"""
from datetime import date

from app.core.workflow import WorkflowSpec, TransitionContext
from app.legal.models.contracts import Contract


def _activated(c: Contract, ctx: TransitionContext) -> None:
    if c.effective_date is None:
        c.effective_date = date.today()


CONTRACT_WORKFLOW = WorkflowSpec(
    domain="legal",
    entity_type="contract",
    model=Contract,
    transitions={
        "DRAFT": ["IN_REVIEW"],
        "IN_REVIEW": ["APPROVED", "DRAFT"],
        "APPROVED": ["SIGNED", "IN_REVIEW"],
        "SIGNED": ["ACTIVE", "TERMINATED"],
        "ACTIVE": ["EXPIRED", "TERMINATED"],
    },
    on_enter={"ACTIVE": _activated},
)

SPECS = {"contract": CONTRACT_WORKFLOW}
