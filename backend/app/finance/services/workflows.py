"""
KAEOS Finance — Workflow Specs
Declarative state machines for AP invoices and expense reports; every
transition flows through app.core.workflow.apply_transition.
"""
from app.core.workflow import WorkflowSpec, TransitionContext
from app.finance.models.accounts_payable import Invoice
from app.finance.models.expense import ExpenseReport


def _invoice_approved(inv: Invoice, ctx: TransitionContext) -> None:
    inv.approved_by = ctx.actor
    inv.approved_at = ctx.now


def _invoice_paid(inv: Invoice, ctx: TransitionContext) -> None:
    inv.amount_paid = inv.total_amount
    inv.balance_due = 0


INVOICE_WORKFLOW = WorkflowSpec(
    domain="finance",
    entity_type="invoice",
    model=Invoice,
    transitions={
        "DRAFT": ["PENDING_APPROVAL", "VOIDED"],
        "PENDING_APPROVAL": ["APPROVED", "DISPUTED", "VOIDED"],
        "APPROVED": ["PARTIALLY_PAID", "PAID", "DISPUTED", "VOIDED"],
        "PARTIALLY_PAID": ["PAID", "DISPUTED"],
        "OVERDUE": ["PARTIALLY_PAID", "PAID", "DISPUTED"],
        "DISPUTED": ["PENDING_APPROVAL", "VOIDED"],
    },
    on_enter={
        "APPROVED": _invoice_approved,
        "PAID": _invoice_paid,
    },
)


def _expense_approved(rep: ExpenseReport, ctx: TransitionContext) -> None:
    rep.approver_id = ctx.actor
    rep.approved_at = ctx.now
    if not rep.approved_amount:
        rep.approved_amount = rep.total_amount


def _expense_rejected(rep: ExpenseReport, ctx: TransitionContext) -> None:
    if ctx.note:
        rep.rejection_reason = ctx.note


def _expense_submitted(rep: ExpenseReport, ctx: TransitionContext) -> None:
    rep.submitted_at = ctx.now


def _expense_reimbursed(rep: ExpenseReport, ctx: TransitionContext) -> None:
    rep.reimbursed_amount = rep.approved_amount or rep.total_amount


EXPENSE_REPORT_WORKFLOW = WorkflowSpec(
    domain="finance",
    entity_type="expense_report",
    model=ExpenseReport,
    transitions={
        "DRAFT": ["SUBMITTED"],
        "SUBMITTED": ["PENDING_APPROVAL", "REJECTED"],
        "PENDING_APPROVAL": ["APPROVED", "REJECTED"],
        "APPROVED": ["REIMBURSED", "PARTIALLY_REIMBURSED"],
        "PARTIALLY_REIMBURSED": ["REIMBURSED"],
        "REJECTED": ["DRAFT"],
    },
    on_enter={
        "SUBMITTED": _expense_submitted,
        "APPROVED": _expense_approved,
        "REJECTED": _expense_rejected,
        "REIMBURSED": _expense_reimbursed,
    },
)

SPECS = {
    "invoice": INVOICE_WORKFLOW,
    "expense_report": EXPENSE_REPORT_WORKFLOW,
}
