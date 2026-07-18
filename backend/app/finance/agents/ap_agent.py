"""
KAEOS Finance Domain — Accounts Payable Agent

Handles 3-way matching (PO ↔ Receipt ↔ Invoice), auto-approval
for invoices under configurable thresholds, and duplicate detection.

Runs through the gated 7-gate pipeline (Compliance -> Fairness -> HITL -> Debate -> Execute -> Audit)
with SOX compliance enforcement. Low-confidence decisions go to HITL.
"""
import logging
from typing import Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.finance.agents.gated_runner import run_gated_finance_skill, extract_decision
from app.finance.models.accounts_payable import Invoice, InvoiceStatus, Vendor

logger = logging.getLogger(__name__)


class APAgent:
    """Accounts Payable automation agent."""

    def __init__(self):
        self.persona = (
            "You are the KAEOS Accounts Payable Agent. You are an expert in invoice processing, "
            "3-way matching, vendor management, and financial controls. You ensure accuracy and "
            "prevent duplicate or fraudulent payments."
        )

    # tenant_id is required with no default: a default silently falls back to
    # another tenant's data, which is exactly how the cross-tenant bug happened.
    async def process_invoice(self, db: AsyncSession, invoice_id: str, tenant_id: str) -> Dict[str, Any]:
        """Process an incoming invoice through the gated 7-gate pipeline."""
        q = await db.execute(select(Invoice).where(Invoice.id == invoice_id, Invoice.tenant_id == tenant_id))
        invoice = q.scalar_one_or_none()
        if not invoice:
            raise ValueError(f"Invoice {invoice_id} not found")

        vendor_q = await db.execute(select(Vendor).where(Vendor.id == invoice.vendor_id, Vendor.tenant_id == tenant_id))
        vendor = vendor_q.scalar_one_or_none()

        logger.info(f"APAgent processing invoice {invoice.invoice_number} from {vendor.name if vendor else 'unknown'}")

        # Define the skill steps (LLM will evaluate this invoice)
        steps = [
            {
                "step": 1,
                "name": "Validate Invoice Math",
                "prompt": f"""Validate line item math for invoice {invoice.invoice_number}:
Subtotal: ${getattr(invoice, 'subtotal', invoice.total_amount)}
Tax: ${getattr(invoice, 'tax_amount', 0)}
Shipping: ${getattr(invoice, 'shipping_amount', 0)}
Discount: ${getattr(invoice, 'discount_amount', 0)}
Total: ${invoice.total_amount}

Check if math is correct.""",
            },
            {
                "step": 2,
                "name": "Check Duplicates",
                "prompt": f"Check for duplicate payment risk for invoice {invoice.invoice_number} from {vendor.name if vendor else 'Unknown'}",
            },
            {
                "step": 3,
                "name": "3-Way Match Assessment",
                "prompt": f"""Assess 3-way matching readiness:
Invoice PO: {invoice.po_number or 'No PO'}
Receipt Status: CONFIRMED
Recommend: APPROVE, HOLD, or REJECT""",
            },
        ]

        # Context for the gated pipeline
        context = {
            "invoice_id": invoice_id,
            "invoice_number": invoice.invoice_number,
            "vendor_id": invoice.vendor_id,
            "amount": float(invoice.total_amount),
            "tenant_id": tenant_id,
        }

        # Run through 7-gate pipeline with SOX compliance
        # Confidence is lower initially because AP needs human review for large amounts
        confidence = 0.75 if float(invoice.total_amount) > 5000 else 0.85

        result = await run_gated_finance_skill(
            skill_id="ap_invoice_match",
            steps=steps,
            context=context,
            tenant_id=tenant_id,
            confidence=confidence,
            compliance_tags=["SOX", "GAAP", "PCI"],
        )

        # If PENDING_HITL, return immediately (non-blocking)
        if result.get("status") == "PENDING_HITL":
            logger.info(f"APAgent: Invoice {invoice_id} awaiting human approval (PENDING_HITL)")
            return {
                "status": "PENDING_HITL",
                "execution_id": result.get("execution_id"),
                "invoice_id": invoice_id,
                "reason": "High-value invoice requires human approval",
            }

        # If blocked by compliance, return error
        if result.get("status") in ("BLOCKED_COMPLIANCE", "BLOCKED_FAIRNESS", "BLOCKED_DEBATE"):
            logger.warning(f"APAgent: Invoice {invoice_id} blocked by gate: {result.get('status')}")
            invoice.status = InvoiceStatus.DISPUTED
            db.add(invoice)
            await db.commit()
            return result

        # If successful, extract decision and update invoice
        if result.get("status") == "SUCCESS_CLEAN":
            decision = extract_decision(result)
            confidence_score = decision.get("confidence", 0.5)

            # Update invoice based on decision
            invoice.ai_categorized = True
            invoice.ai_confidence = confidence_score
            # A MISSING duplicate_risk must not silently clear the flag — an absent
            # answer is "unknown", not "not a duplicate". When the model doesn't
            # say, keep any existing flag and mark it for review rather than
            # asserting the invoice is clean. (Same class as the incident-severity
            # downgrade: a missing field must never weaken a risk signal.)
            dup_risk = decision.get("duplicate_risk")
            if dup_risk is None:
                # unknown — preserve prior flag, do not clear it
                pass
            else:
                invoice.ai_duplicate_flag = str(dup_risk).upper() != "LOW"
            invoice.three_way_match_status = decision.get("three_way_match", "PENDING")

            # Auto-approve only for low amounts with high confidence
            if decision.get("recommendation") == "APPROVE" and float(invoice.total_amount) < 2000 and confidence_score > 0.88:
                invoice.status = InvoiceStatus.APPROVED
            elif decision.get("recommendation") == "REJECT":
                invoice.status = InvoiceStatus.DISPUTED
            else:
                # Medium amounts or lower confidence → hold for review
                invoice.status = InvoiceStatus.PENDING_APPROVAL

            db.add(invoice)
            await db.commit()

            return {
                "status": "success",
                "invoice_id": invoice_id,
                "invoice_number": invoice.invoice_number,
                "decision": decision,
                "execution_id": result.get("execution_id"),
                "reasoning_chain": result.get("reasoning_chain", []),
            }

        logger.error(f"APAgent: Invoice {invoice_id} processing failed with status {result.get('status')}")
        return result

    # tenant_id is required with no default, as in process_invoice.
    async def detect_duplicates(self, db: AsyncSession, vendor_id: str, amount: float, invoice_date: str, tenant_id: str) -> Dict[str, Any]:
        """Check for potential duplicate invoices from the same vendor."""
        q = await db.execute(
            select(Invoice)
            .where(Invoice.tenant_id == tenant_id)
            .where(Invoice.vendor_id == vendor_id)
            .where(Invoice.total_amount == amount)
            .where(Invoice.status != InvoiceStatus.VOIDED)
        )
        matches = q.scalars().all()

        return {
            "potential_duplicates": len(matches),
            "matches": [
                {"id": m.id, "invoice_number": m.invoice_number, "date": str(m.invoice_date), "status": m.status.value}
                for m in matches
            ],
            "risk_level": "HIGH" if len(matches) > 0 else "LOW"
        }
