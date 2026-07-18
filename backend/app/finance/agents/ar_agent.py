"""KAEOS Finance Domain - AR Dunning Agent

Context-grounding: the agent loads the real entity and reasons over its
content. Passing only an opaque id left the model classifying an identifier
(confirmed ungrounded on real onboarded data), so facts are non-optional.
"""
from typing import Any, Dict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.finance.agents.gated_runner import run_gated_finance_skill
from app.finance.models.accounts_receivable import CustomerInvoice
from app.services.json_utils import plain_facts


def _v(x):
    return getattr(x, "value", x)


class ARAgent:
    # tenant_id is required with no default: a default silently falls back to
    # another tenant's data.
    async def generate_dunning(self, db: AsyncSession, invoice_id: str, tenant_id: str, has_human_approver: bool = False) -> Dict[str, Any]:
        invoice = (await db.execute(
            select(CustomerInvoice).where(CustomerInvoice.id == invoice_id, CustomerInvoice.tenant_id == tenant_id)
        )).scalar_one_or_none()
        if not invoice:
            raise ValueError(f"Customer invoice {invoice_id} not found")

        facts = {
            "invoice_number": invoice.invoice_number,
            "status": _v(invoice.status),
            "total_amount": invoice.total_amount,
            "balance_due": invoice.balance_due,
            "currency": invoice.currency,
            "invoice_date": str(invoice.invoice_date) if invoice.invoice_date else None,
            "due_date": str(invoice.due_date) if invoice.due_date else None,
            "dunning_level": invoice.dunning_level,
            "last_dunning_date": str(invoice.last_dunning_date) if invoice.last_dunning_date else None,
        }
        facts = plain_facts(facts)
        return await run_gated_finance_skill(
            skill_id="finance_ar_dunning",
            steps=[{"step": 1, "name": "Generate",
                    "prompt": f"Generate the next dunning letter for this overdue invoice: {facts}"}],
            context={
                "invoice_id": invoice_id, "tenant_id": tenant_id, "has_human_approver": has_human_approver, **facts,
                "instruction": "Output strict JSON: {dunning_level, tone, letter_body, escalate_to_collections}.",
            },
            tenant_id=tenant_id,
        )
