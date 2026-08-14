"""
KAEOS Lending Domain - Seed Script

Comprehensive demo data for tenant_acme: four credit policies (personal, auto,
mortgage, small-business), a realistic book of applications across products and
protected classes, and - for the applications already decided - the matching
underwriting decisions (with TILA/Reg Z disclosures on approvals) and ECOA
adverse-action notices (specific principal reasons, sent within 30 days) on
denials. Decisions are computed deterministically from the policy so the numbers
are internally consistent and the four-fifths fair-lending monitor has real
approval-rate spread to analyze.

Protected-class attributes are stored ONLY for fair-lending analysis, never as a
credit input - the decision below uses score / DTI / income / amount only.
"""
import asyncio
import uuid
from datetime import datetime, timezone, timedelta, date
from decimal import Decimal

from app.core.database import AsyncSessionLocal, async_engine
from app.lending.models.core import (
    AdverseActionNotice, CreditPolicy, LoanApplication, LoanStatus,
    UnderwritingDecision,
)
from app.models.domain import Base

TENANT = "tenant_acme"


def _id():
    return str(uuid.uuid4())


def _ago(days):
    return datetime.now(timezone.utc) - timedelta(days=days)


# product -> policy thresholds (min_score, max_dti, min_income, max_amount, base_apr)
_POLICIES = {
    "personal_loan":  dict(min_credit_score=640, max_dti_ratio=0.45, min_annual_income=24000,  max_amount=50000,  base_apr=12.5),
    "auto_loan":      dict(min_credit_score=620, max_dti_ratio=0.50, min_annual_income=30000,  max_amount=75000,  base_apr=8.9),
    "mortgage":       dict(min_credit_score=660, max_dti_ratio=0.43, min_annual_income=48000,  max_amount=750000, base_apr=6.75),
    "small_business": dict(min_credit_score=680, max_dti_ratio=0.40, min_annual_income=100000, max_amount=250000, base_apr=10.25),
}

# (app#, name, product, amount, term_months, score, income, dti, protected_class, days_ago_decided)
# days_ago_decided = None -> still RECEIVED (no decision yet).
_APPS = [
    ("LN-1001", "Jordan Rivera",   "personal_loan",  18000, 36, 742,  96000, 0.28, {"gender": "female", "ethnicity": "hispanic"}, 12),
    ("LN-1002", "Sam Okafor",      "personal_loan",  25000, 48, 705, 120000, 0.31, {"gender": "male",   "ethnicity": "black"},    11),
    ("LN-1003", "Alex Chen",       "personal_loan",  32000, 60, 598,  41000, 0.58, {"gender": "male",   "ethnicity": "asian"},    10),
    ("LN-1004", "Priya Nair",      "personal_loan",  75000, 60, 760, 210000, 0.22, {"gender": "female", "ethnicity": "asian"},     9),
    ("LN-1005", "Marcus Bell",     "auto_loan",      41000, 72, 688,  84000, 0.36, {"gender": "male",   "ethnicity": "black"},     8),
    ("LN-1006", "Dana White",      "auto_loan",      52000, 72, 610,  58000, 0.54, {"gender": "female", "ethnicity": "white"},     7),
    ("LN-1007", "Sofia Marquez",   "mortgage",      420000, 360, 774, 165000, 0.33, {"gender": "female", "ethnicity": "hispanic"},  6),
    ("LN-1008", "Ethan Cole",      "mortgage",      610000, 360, 651,  92000, 0.47, {"gender": "male",   "ethnicity": "white"},     5),
    ("LN-1009", "Amina Yusuf",     "mortgage",      380000, 360, 712, 138000, 0.29, {"gender": "female", "ethnicity": "black"},     5),
    ("LN-1010", "Grace Kim",       "small_business",180000, 60, 724, 240000, 0.34, {"gender": "female", "ethnicity": "asian"},     4),
    ("LN-1011", "Tomas Alvarez",   "small_business",300000, 84, 701, 320000, 0.31, {"gender": "male",   "ethnicity": "hispanic"},  3),
    ("LN-1012", "Ruth Feldman",    "small_business", 90000, 48, 668,  95000, 0.44, {"gender": "female", "ethnicity": "white"},     3),
    # Still in intake (no decision yet) - populates the RECEIVED queue.
    ("LN-1013", "Noah Bennett",    "personal_loan",  22000, 36, 731, 102000, 0.27, {"gender": "male",   "ethnicity": "white"},   None),
    ("LN-1014", "Leila Haddad",    "auto_loan",      36000, 60, 699,  76000, 0.38, {"gender": "female", "ethnicity": "hispanic"}, None),
]


def _decide(product, amount, score, income, dti):
    """Deterministic policy check - mirrors the underwriting service. Returns
    (decision, reasons). Reasons are the specific principal reasons Reg B wants."""
    p = _POLICIES[product]
    reasons = []
    if score < p["min_credit_score"]:
        reasons.append(f"Credit score {score} is below the required {p['min_credit_score']} for this product")
    if dti > p["max_dti_ratio"]:
        reasons.append(f"Debt-to-income ratio {dti:.0%} exceeds the {p['max_dti_ratio']:.0%} maximum")
    if income < p["min_annual_income"]:
        reasons.append(f"Annual income ${income:,.0f} is below the ${p['min_annual_income']:,.0f} minimum")
    if amount > p["max_amount"]:
        reasons.append(f"Requested ${amount:,.0f} exceeds the ${p['max_amount']:,.0f} program limit")
    return ("APPROVE", []) if not reasons else ("DENY", reasons)


def _apr(product, score):
    """Risk-based APR: base + a spread that shrinks as score rises."""
    base = _POLICIES[product]["base_apr"]
    spread = max(0.0, (760 - score)) / 40.0     # ~0 at 760, ~4pts at 600
    return round(base + spread, 2)


async def seed():
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as db:
        for product, p in _POLICIES.items():
            db.add(CreditPolicy(id=_id(), tenant_id=TENANT, product=product,
                                is_active=True, **p))

        approvals = denials = pending = 0
        for (num, name, product, amount, term, score, income, dti, pclass, decided_ago) in _APPS:
            app_id = _id()
            if decided_ago is None:
                status = LoanStatus.RECEIVED.value
            else:
                decision, reasons = _decide(product, amount, score, income, dti)
                status = LoanStatus.APPROVED.value if decision == "APPROVE" else LoanStatus.DENIED.value
            db.add(LoanApplication(
                id=app_id, tenant_id=TENANT, application_number=num, applicant_name=name,
                product=product, credit_purpose="business" if product == "small_business" else "consumer",
                amount=Decimal(str(amount)), term_months=term, credit_score=score,
                annual_income=Decimal(str(income)), dti_ratio=Decimal(str(dti)),
                monthly_debt=Decimal(str(round(income * dti / 12, 2))),
                protected_class=pclass, status=status,
                intake_score=Decimal(str(round(min(1.0, score / 850), 4)))))

            if decided_ago is None:
                pending += 1
                continue

            dec_id = _id()
            apr = _apr(product, score)
            if decision == "APPROVE":
                approvals += 1
                fin_charge = round(amount * (apr / 100) * (term / 12), 2)
                db.add(UnderwritingDecision(
                    id=dec_id, tenant_id=TENANT, application_id=app_id, decision="APPROVE",
                    reasons=["Meets credit-score, DTI, income and program-limit policy"],
                    confidence=Decimal("0.92"), decided_by="underwriter_agent",
                    decided_at=_ago(decided_ago), gate_status="SUCCESS_CLEAN",
                    apr=Decimal(str(apr)), finance_charge=Decimal(str(fin_charge)),
                    amount_financed=Decimal(str(amount)),
                    total_of_payments=Decimal(str(round(amount + fin_charge, 2)))))
            else:
                denials += 1
                db.add(UnderwritingDecision(
                    id=dec_id, tenant_id=TENANT, application_id=app_id, decision="DENY",
                    reasons=reasons, confidence=Decimal("0.95"), decided_by="underwriter_agent",
                    decided_at=_ago(decided_ago), gate_status="SUCCESS_CLEAN"))
                db.add(AdverseActionNotice(
                    id=_id(), tenant_id=TENANT, application_id=app_id, decision_id=dec_id,
                    specific_reasons=reasons,
                    body=("We are unable to approve your application at this time for the "
                          "following principal reason(s): " + "; ".join(reasons) +
                          ". You have the right to a free copy of your credit report and to "
                          "dispute its accuracy. (ECOA / Reg B, 12 CFR 1002.9)"),
                    decision_date=date.today() - timedelta(days=decided_ago),
                    sent_at=_ago(decided_ago - 1 if decided_ago > 1 else 0),
                    within_30_days=True))

        await db.commit()
        print("[SUCCESS] Seeded Lending database:")
        print(f"   - {len(_APPS)} applications ({approvals} approved, {denials} denied, "
              f"{pending} in intake), {len(_POLICIES)} credit policies, "
              f"{denials} adverse-action notices")


if __name__ == "__main__":
    asyncio.run(seed())
