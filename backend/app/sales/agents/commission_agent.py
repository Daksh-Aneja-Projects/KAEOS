"""
KAEOS Sales Domain — Commission Agent
"""
import logging
from typing import Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.sales.models.commission import CommissionPlan, CommissionCalculation

logger = logging.getLogger(__name__)

class CommissionAgent:
    """Agent for calculating sales rep commission payouts on closed opportunities."""

    def __init__(self):
        pass

    async def calculate_payout(self, db: AsyncSession, calculation_id: str, tenant_id: str,
                               *, approver: str = "system") -> Dict[str, Any]:
        """Calculates exact commission shares based on quota attainment and triggers approval flags."""
        q = await db.execute(select(CommissionCalculation).where(
            CommissionCalculation.id == calculation_id,
            CommissionCalculation.tenant_id == tenant_id))
        calc = q.scalar_one_or_none()

        if not calc:
            raise ValueError(f"Commission calculation {calculation_id} not found")

        logger.info(f"CommissionAgent running payout calculations for transaction: {calc.id}")

        plan_q = await db.execute(select(CommissionPlan).where(
            CommissionPlan.id == calc.plan_id, CommissionPlan.tenant_id == tenant_id))
        plan = plan_q.scalar_one()

        # Payout = Deal Value × Commission Rate.
        # Use the plan's rate as-is: a legitimate 0% (draw-only / non-commissioned
        # plan) must NOT fall through to the 10% default. `or` treats 0.0 as
        # missing, so guard on None explicitly.
        rate_pct = plan.base_commission_rate if plan.base_commission_rate is not None else 10.00
        rate = float(rate_pct) / 100.00
        payout = float(calc.deal_value) * rate

        # Payouts do NOT self-approve. Small amounts auto-approve; anything at or
        # above the threshold routes to a human — an agent must never rubber-stamp
        # a large commission with no oversight.
        AUTO_APPROVE_LIMIT = 10_000.0
        auto_approved = payout < AUTO_APPROVE_LIMIT
        calc.calculated_payout = payout
        calc.is_approved = auto_approved

        db.add(calc)

        # M16: a commission payout is money out and must not be committed with no
        # audit trail. Hash-chain a ledger entry recording the amount, the approver
        # AND the beneficiary rep (traced through the opportunity), so a self-
        # approval is detectable on review even though the operator/rep identity
        # spaces are not directly comparable for a hard four-eyes block.
        beneficiary = None
        try:
            from app.sales.models.pipeline import Opportunity
            if calc.opportunity_id:
                opp = (await db.execute(select(Opportunity).where(
                    Opportunity.id == calc.opportunity_id,
                    Opportunity.tenant_id == tenant_id))).scalar_one_or_none()
                beneficiary = getattr(opp, "assigned_rep_id", None)
            from app.services.provenance import append_ledger_event
            await append_ledger_event(
                db, tenant_id=tenant_id, event_type="COMMISSION_PAYOUT",
                reasoning=(f"Commission payout ${payout:,.2f} on deal ${float(calc.deal_value):,.2f} "
                           f"at {rate * 100:.2f}%; {'auto-approved' if auto_approved else 'routed to human approval'} "
                           f"(limit ${AUTO_APPROVE_LIMIT:,.0f}). approver={approver} beneficiary_rep={beneficiary}"),
                evidence_ids=[calc.id, calc.plan_id],
                scope=calc.id, commit=False)
        except Exception as e:
            logger.error("[Commission] LEDGER FAILED for payout %s: %s", calc.id, e)

        await db.commit()

        return {
            "calculation_id": calc.id,
            "deal_value": float(calc.deal_value),
            "rate_applied": rate,
            "calculated_payout": payout,
            "is_approved": auto_approved,
            "status": "APPROVED" if auto_approved else "PENDING_HUMAN_APPROVAL",
            "reason": None if auto_approved else f"Payout ${payout:,.2f} is at or above the ${AUTO_APPROVE_LIMIT:,.0f} auto-approve limit, so it requires human approval",
        }
