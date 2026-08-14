"""
KAEOS Lending Domain - Intake Agent

Deterministic validation + readiness scoring of an incoming loan application.
Makes no credit decision (that is the Underwriter Agent), so it does not need
the decision-gate pipeline - it validates required fields, computes a triage
score, and leaves an evidence trail.
"""
import logging
from typing import Any, Dict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.lending.models.core import CreditPolicy, LoanApplication, LoanStatus
from app.lending.services.underwriting import evaluate_policy
from app.services.provenance import append_ledger_event

logger = logging.getLogger(__name__)

_REQUIRED = ("applicant_name", "amount", "product")


class IntakeAgent:
    def __init__(self):
        self.persona = "You are the KAEOS Lending Intake Agent."

    async def validate_and_score(self, db: AsyncSession, application_id: str,
                                 tenant_id: str) -> Dict[str, Any]:
        q = await db.execute(select(LoanApplication).where(
            LoanApplication.id == application_id,
            LoanApplication.tenant_id == tenant_id))
        app = q.scalar_one_or_none()
        if not app:
            raise ValueError(f"Loan application {application_id} not found")

        missing = [f for f in _REQUIRED if getattr(app, f, None) in (None, "", 0)]
        errors = list(missing and [f"Missing required field: {m}" for m in missing] or [])
        if app.amount is not None and app.amount <= 0:
            errors.append("Loan amount must be positive.")

        pol_q = await db.execute(select(CreditPolicy).where(
            CreditPolicy.tenant_id == tenant_id,
            CreditPolicy.product == app.product))
        policy = pol_q.scalar_one_or_none()
        verdict = evaluate_policy(app, policy)

        app.intake_score = verdict["intake_score"]
        app.status = LoanStatus.IN_REVIEW.value if not errors else LoanStatus.RECEIVED.value
        db.add(app)
        await append_ledger_event(
            db, tenant_id=tenant_id, event_type="LOAN_INTAKE",
            reasoning=f"Intake validated application {app.application_number}; "
                      f"score {verdict['intake_score']}; "
                      f"{'valid' if not errors else 'incomplete: ' + '; '.join(errors)}.",
            evidence_ids=[app.id], scope=app.id, commit=True)

        return {
            "status": "valid" if not errors else "incomplete",
            "application_id": app.id,
            "intake_score": verdict["intake_score"],
            "errors": errors,
            "preliminary_decision": verdict["decision"],
        }
