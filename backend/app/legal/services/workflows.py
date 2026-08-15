"""
KAEOS Legal — Workflow Specs
Contract lifecycle: draft → review → approved → signed → active → expired /
terminated. Activation stamps the effective date when counsel left it blank.
Matter lifecycle: new → in progress / on hold → resolved → closed. Obligation
lifecycle: pending / overdue → completed / waived.
"""
from datetime import date

from app.core.workflow import WorkflowSpec, TransitionContext
from app.legal.models.compliance import ComplianceObligation
from app.legal.models.contracts import Contract
from app.legal.models.core import LegalMatter
from app.legal.services.compliance_gates import guard_matter_closure


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
    # Terminating a live contract is a legal event - admin only.
    role_requirements={"TERMINATED": "admin"},
    sla_hours={"IN_REVIEW": 120, "APPROVED": 120, "SIGNED": 72},
)


def _resolved(m: LegalMatter, ctx: TransitionContext) -> None:
    if ctx.note:
        m.resolution = ctx.note


MATTER_WORKFLOW = WorkflowSpec(
    domain="legal",
    entity_type="matter",
    model=LegalMatter,
    transitions={
        "NEW": ["IN_PROGRESS", "ON_HOLD", "CLOSED"],
        "IN_PROGRESS": ["ON_HOLD", "RESOLVED", "CLOSED"],
        "ON_HOLD": ["IN_PROGRESS", "CLOSED"],
        "RESOLVED": ["CLOSED"],
    },
    on_enter={"RESOLVED": _resolved},
    # Closing a matter file is a records-disposition event - screened by the
    # LEGAL_HOLD / RETENTION_SCHEDULE checkers (app/compliance/checkers/legal.py)
    # and admin-gated like contract termination.
    guards={"CLOSED": guard_matter_closure},
    role_requirements={"CLOSED": "admin"},
    sla_hours={"NEW": 72, "IN_PROGRESS": 720},
)

OBLIGATION_WORKFLOW = WorkflowSpec(
    domain="legal",
    entity_type="obligation",
    model=ComplianceObligation,
    transitions={
        "PENDING": ["COMPLETED", "OVERDUE", "WAIVED"],
        "OVERDUE": ["COMPLETED", "WAIVED"],
    },
    sla_hours={"PENDING": 720},
)

SPECS = {
    "contract": CONTRACT_WORKFLOW,
    "matter": MATTER_WORKFLOW,
    "obligation": OBLIGATION_WORKFLOW,
}
