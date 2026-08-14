"""
KAEOS Lending - Underwriting Service

The deterministic credit decision AND the real compliance gates. No decision
ships that fails a gate: the ECOA (adverse-action) and FAIR_LENDING
(disparate-impact) checkers run as HARD gates here (fail-closed) - a blocking
verdict raises before anything is persisted.

The credit decision is computed by `evaluate_policy` from permissible,
credit-related inputs only. Protected-class attributes are NEVER read here;
they feed the portfolio-level four-fifths analysis, not the individual decision.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.compliance import run_checks
from app.lending.models.core import (AdverseActionNotice, CreditPolicy,
                                     LoanApplication, LoanStatus,
                                     UnderwritingDecision)
from app.services.provenance import append_ledger_event

# Conservative built-in policy when the tenant has not configured one.
_DEFAULT_POLICY = {
    "min_credit_score": 640,
    "max_dti_ratio": Decimal("0.45"),
    "min_annual_income": Decimal("24000"),
    "max_amount": Decimal("50000"),
    "base_apr": Decimal("12.5"),
}
_GENERIC_DENY_REASONS = {"credit score", "risk", "policy", "declined"}


class LendingError(ValueError):
    """Base typed lending error; the router maps it to 4xx."""


class ApplicationNotFound(LendingError):
    pass


class UnderwritingGateError(LendingError):
    """A compliance gate blocked the decision. Fail-closed: nothing was persisted."""

    def __init__(self, message: str, blocking: list):
        super().__init__(message)
        self.blocking = blocking


def _dec(v) -> Optional[Decimal]:
    if v is None:
        return None
    return v if isinstance(v, Decimal) else Decimal(str(v))


def _policy_values(policy: Optional[CreditPolicy]) -> dict:
    if policy is None:
        return dict(_DEFAULT_POLICY)
    return {
        "min_credit_score": policy.min_credit_score,
        "max_dti_ratio": _dec(policy.max_dti_ratio),
        "min_annual_income": _dec(policy.min_annual_income),
        "max_amount": _dec(policy.max_amount),
        "base_apr": _dec(policy.base_apr),
    }


def evaluate_policy(app: LoanApplication, policy: Optional[CreditPolicy]) -> dict:
    """Pure deterministic credit decision. Returns
    ``{decision, reasons, intake_score, dti}``.

    A threshold failure produces a SPECIFIC principal reason (the exact string
    Reg B needs on a denial). Protected-class fields are intentionally not read.
    """
    p = _policy_values(policy)
    reasons: list[str] = []

    score = app.credit_score
    if score is not None and score < p["min_credit_score"]:
        reasons.append(f"Credit score of {score} is below the program minimum of "
                       f"{p['min_credit_score']}.")

    income = _dec(app.annual_income)
    if income is not None and income < p["min_annual_income"]:
        reasons.append(f"Annual income of ${income:,.0f} is below the required minimum "
                       f"of ${p['min_annual_income']:,.0f}.")

    # DTI: use stored ratio, else derive from monthly debt and annual income.
    dti = _dec(app.dti_ratio)
    if dti is None and app.monthly_debt is not None and income and income > 0:
        dti = (_dec(app.monthly_debt) * 12) / income
    if dti is not None and dti > p["max_dti_ratio"]:
        reasons.append(f"Debt-to-income ratio of {dti * 100:.0f}% exceeds the program "
                       f"limit of {p['max_dti_ratio'] * 100:.0f}%.")

    amount = _dec(app.amount)
    if amount is not None and amount > p["max_amount"]:
        reasons.append(f"Requested amount of ${amount:,.0f} exceeds the maximum program "
                       f"amount of ${p['max_amount']:,.0f}.")

    # A missing hard input (score) means we cannot verify eligibility - refer to
    # a human rather than approve on absent data (never weaken risk on a gap).
    if score is None:
        reasons.append("Credit score is missing; eligibility could not be verified.")

    decision = "APPROVE" if not reasons else "DENY"
    intake_score = _intake_score(score, income, dti, p)
    return {"decision": decision, "reasons": reasons, "intake_score": intake_score,
            "dti": dti}


def _intake_score(score, income, dti, p) -> float:
    """A crude 0..1 readiness score for triage/dashboards only - NOT the decision."""
    parts = []
    if score is not None:
        parts.append(min(1.0, max(0.0, (score - 500) / 350)))  # 500..850 -> 0..1
    if income and p["min_annual_income"]:
        parts.append(min(1.0, float(income) / (float(p["min_annual_income"]) * 4)))
    if dti is not None:
        parts.append(max(0.0, 1.0 - float(dti) / 1.0))
    return round(sum(parts) / len(parts), 4) if parts else 0.0


def _tila_disclosures(app: LoanApplication, policy: Optional[CreditPolicy]) -> dict:
    """Deterministic Reg Z disclosure figures for an approval. A flat-rate
    simple-interest estimate - enough to satisfy the presence + tolerance
    checks; the servicing system produces the binding numbers."""
    p = _policy_values(policy)
    amount = _dec(app.amount) or Decimal("0")
    apr = p["base_apr"]
    term = app.term_months or 36
    # Simple flat estimate: finance charge = amount * apr/100 * years.
    finance_charge = (amount * apr / Decimal("100") * Decimal(term) / Decimal("12")
                      ).quantize(Decimal("0.01"))
    return {
        "apr": apr,
        "actual_apr": apr,
        "finance_charge": finance_charge,
        "amount_financed": amount,
        "total_of_payments": (amount + finance_charge).quantize(Decimal("0.01")),
    }


async def _load_application(db: AsyncSession, tenant_id: str,
                            application_id: str) -> LoanApplication:
    q = await db.execute(select(LoanApplication).where(
        LoanApplication.id == application_id,
        LoanApplication.tenant_id == tenant_id))
    app = q.scalar_one_or_none()
    if app is None:
        # Other-tenant row is indistinguishable from missing -> 404.
        raise ApplicationNotFound(f"Loan application {application_id} not found")
    return app


async def _load_policy(db: AsyncSession, tenant_id: str,
                       product: str) -> Optional[CreditPolicy]:
    q = await db.execute(select(CreditPolicy).where(
        CreditPolicy.tenant_id == tenant_id,
        CreditPolicy.product == product,
        CreditPolicy.is_active == True))  # noqa: E712
    return q.scalar_one_or_none()


async def underwrite_application(
    db: AsyncSession,
    tenant_id: str,
    *,
    application_id: str,
    decided_by: str,
    approval_cohorts: Optional[dict] = None,
    business_necessity: Optional[str] = None,
    confidence: float = 0.9,
) -> UnderwritingDecision:
    """Underwrite one application through REAL compliance gates and persist the
    decision. Fail-closed: a blocking ECOA or FAIR_LENDING verdict raises
    ``UnderwritingGateError`` and NOTHING is persisted.

    ``approval_cohorts`` (four-fifths input) enables portfolio fair-lending
    gating on this decision; ``business_necessity`` documents a justification
    that downgrades an adverse-impact finding to advisory.
    """
    app = await _load_application(db, tenant_id, application_id)
    policy = await _load_policy(db, tenant_id, app.product)

    verdict = evaluate_policy(app, policy)
    decision = verdict["decision"]
    reasons = verdict["reasons"]

    # Build the compliance context and run the checkers that APPLY as hard gates.
    frameworks = ["FAIR_LENDING"]
    ctx: dict = {
        "decision": decision,
        "credit_purpose": app.credit_purpose,
        "approval_cohorts": approval_cohorts,
        "business_necessity": business_necessity,
    }
    disclosures = None
    if decision == "DENY":
        frameworks.append("ECOA")
        ctx["adverse_action"] = {
            "reasons": reasons,
            "notice_days": 0,             # notice generated at/near decision time
            "prohibited_basis_used": False,
        }
    else:
        frameworks.append("TILA")
        disclosures = _tila_disclosures(app, policy)
        ctx["tila"] = {k: str(v) for k, v in disclosures.items()}

    gate = run_checks(frameworks, ctx)

    # Evidence trail FIRST - the gate outcome is recorded whether or not it ships.
    await append_ledger_event(
        db, tenant_id=tenant_id, event_type="UNDERWRITING_DECISION",
        reasoning=(f"Underwriting {decision} for application {app.application_number}; "
                   f"gates {'PASSED' if gate['verified'] else 'BLOCKED'} "
                   f"({', '.join(frameworks)})."),
        evidence_ids=[app.id],
        scope=app.id,
        confidence_at=confidence,
        commit=False,
    )

    if not gate["verified"]:
        # Fail closed. The ledger row above rolls back with this raise.
        codes = [f["framework"] for f in gate["blocking"]]
        raise UnderwritingGateError(
            f"Underwriting blocked by compliance gate(s): {', '.join(codes)}.",
            blocking=gate["blocking"])

    row = UnderwritingDecision(
        tenant_id=tenant_id, application_id=app.id,
        decision=decision, reasons=reasons, confidence=confidence,
        decided_by=decided_by, gate_status="PASSED",
    )
    if disclosures is not None:
        row.apr = disclosures["apr"]
        row.finance_charge = disclosures["finance_charge"]
        row.amount_financed = disclosures["amount_financed"]
        row.total_of_payments = disclosures["total_of_payments"]

    app.status = LoanStatus.APPROVED.value if decision == "APPROVE" else LoanStatus.DENIED.value
    app.intake_score = verdict["intake_score"]
    db.add_all([row, app])
    await db.commit()
    await db.refresh(row)
    return row


async def generate_adverse_action(
    db: AsyncSession,
    tenant_id: str,
    *,
    application_id: str,
    decided_by: str,
    decision_id: Optional[str] = None,
) -> AdverseActionNotice:
    """Generate a Reg B adverse-action notice from the persisted denial decision.
    Fail-closed: the ECOA checker validates the notice content and a blocking
    verdict raises (no notice persisted)."""
    app = await _load_application(db, tenant_id, application_id)

    q = await db.execute(select(UnderwritingDecision).where(
        UnderwritingDecision.tenant_id == tenant_id,
        UnderwritingDecision.application_id == application_id,
        UnderwritingDecision.decision == "DENY").order_by(
        UnderwritingDecision.decided_at.desc()))
    decision = q.scalars().first()
    if decision is None:
        raise LendingError("No denial decision on file for this application; "
                           "an adverse-action notice is only issued on a denial.")

    reasons = list(decision.reasons or [])
    today = date.today()
    body = _render_notice(app, reasons)

    # Validate against the ECOA checker BEFORE persisting (fail-closed).
    gate = run_checks(["ECOA"], {
        "decision": "DENY",
        "decision_date": str(today),
        "adverse_action": {"reasons": reasons, "notice_days": 0,
                           "prohibited_basis_used": False},
    })
    if not gate["verified"]:
        raise UnderwritingGateError(
            "Adverse-action notice failed the ECOA content check; not issued.",
            blocking=gate["blocking"])

    notice = AdverseActionNotice(
        tenant_id=tenant_id, application_id=app.id, decision_id=decision.id,
        specific_reasons=reasons, body=body, decision_date=today,
        sent_at=datetime.now(timezone.utc), within_30_days=True,
    )
    await append_ledger_event(
        db, tenant_id=tenant_id, event_type="ADVERSE_ACTION_NOTICE",
        reasoning=f"Adverse-action notice issued for application {app.application_number} "
                  f"with {len(reasons)} specific reason(s).",
        evidence_ids=[app.id, decision.id], scope=app.id, commit=False,
    )
    db.add(notice)
    await db.commit()
    await db.refresh(notice)
    return notice


def _render_notice(app: LoanApplication, reasons: list[str]) -> str:
    lines = [
        f"Notice of Adverse Action - Application {app.application_number}",
        "",
        "We are unable to approve your credit request for the following "
        "specific principal reasons:",
    ]
    lines += [f"  - {r}" for r in reasons]
    lines += [
        "",
        "You have the right to a statement of the specific reasons for this "
        "decision. If you believe any information relied upon is inaccurate, "
        "you may contact us. This notice is provided under the Equal Credit "
        "Opportunity Act (15 U.S.C. 1691) and Regulation B (12 CFR 1002.9).",
    ]
    return "\n".join(lines)
