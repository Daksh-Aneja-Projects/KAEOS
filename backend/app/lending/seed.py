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
import logging
from datetime import datetime, timezone, timedelta, date
from decimal import Decimal

from sqlalchemy import func as sqlfunc, select

from app.core.database import AsyncSessionLocal, async_engine
from app.core.domain_seed import SEED_TENANT as TENANT, already_seeded, new_id, run_standalone
from app.lending.models.core import (
    AdverseActionNotice, CreditPolicy, LoanApplication, LoanStatus,
    UnderwritingDecision,
)
from app.lending.models.servicing import (CollectionCase, CollectionCaseStatus,
                                          ServicedLoan, ServicingStatus)
from app.lending.services.servicing import (build_amortization_schedule,
                                            delinquency_bucket)

logger = logging.getLogger(__name__)


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
# days_ago_decided = None -> still RECEIVED (no decision yet). The six approved
# rows converted to serviced loans below (LN-1001/1002/1005/1007/1009/1010) are
# decided much further back than the rest of the book so their payment
# schedules have real, internally-consistent history (some current, some
# delinquent) instead of a freshly-funded loan claiming months of payments.
_APPS = [
    ("LN-1001", "Jordan Rivera",   "personal_loan",  18000, 36, 742,  96000, 0.28, {"gender": "female", "ethnicity": "hispanic"}, 380),
    ("LN-1002", "Sam Okafor",      "personal_loan",  25000, 48, 705, 120000, 0.31, {"gender": "male",   "ethnicity": "black"},    300),
    ("LN-1003", "Alex Chen",       "personal_loan",  32000, 60, 598,  41000, 0.58, {"gender": "male",   "ethnicity": "asian"},    10),
    ("LN-1004", "Priya Nair",      "personal_loan",  75000, 60, 760, 210000, 0.22, {"gender": "female", "ethnicity": "asian"},     9),
    ("LN-1005", "Marcus Bell",     "auto_loan",      41000, 72, 688,  84000, 0.36, {"gender": "male",   "ethnicity": "black"},    500),
    ("LN-1006", "Dana White",      "auto_loan",      52000, 72, 610,  58000, 0.54, {"gender": "female", "ethnicity": "white"},     7),
    ("LN-1007", "Sofia Marquez",   "mortgage",      420000, 360, 774, 165000, 0.33, {"gender": "female", "ethnicity": "hispanic"}, 250),
    ("LN-1008", "Ethan Cole",      "mortgage",      610000, 360, 651,  92000, 0.47, {"gender": "male",   "ethnicity": "white"},     5),
    ("LN-1009", "Amina Yusuf",     "mortgage",      380000, 360, 712, 138000, 0.29, {"gender": "female", "ethnicity": "black"},   150),
    ("LN-1010", "Grace Kim",       "small_business",180000, 60, 724, 240000, 0.34, {"gender": "female", "ethnicity": "asian"},   220),
    ("LN-1011", "Tomas Alvarez",   "small_business",300000, 84, 701, 320000, 0.31, {"gender": "male",   "ethnicity": "hispanic"},  3),
    ("LN-1012", "Ruth Feldman",    "small_business", 90000, 48, 668,  95000, 0.44, {"gender": "female", "ethnicity": "white"},     3),
    # Still in intake (no decision yet) - populates the RECEIVED queue.
    ("LN-1013", "Noah Bennett",    "personal_loan",  22000, 36, 731, 102000, 0.27, {"gender": "male",   "ethnicity": "white"},   None),
    ("LN-1014", "Leila Haddad",    "auto_loan",      36000, 60, 699,  76000, 0.38, {"gender": "female", "ethnicity": "hispanic"}, None),
]

# Which approved applications become serviced loans, and how delinquent (0 =
# current). Chosen so the servicing book shows a real spread of buckets.
_SERVICING = {
    "LN-1001": 0,    # current, seasoned book
    "LN-1002": 65,   # lands in the 30-59 DPD bucket - open collections case
    "LN-1005": 95,   # lands in the 90+ DPD bucket / DEFAULT - escalated case
    "LN-1007": 0,    # current
    "LN-1009": 0,    # current
    "LN-1010": 0,    # current
}


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


def _fund_loan(tenant, app_id, num, name, product, amount, term, score, funded_days_ago, delinquent_days=0):
    """Build a ServicedLoan (+ its amortization schedule) that is internally
    consistent with how long ago it funded and how delinquent it is today.
    Returns (ServicedLoan, days_past_due)."""
    principal = Decimal(str(amount))
    apr = Decimal(str(_apr(product, score)))
    funded_at = _ago(funded_days_ago)
    first_due = funded_at.date() + timedelta(days=30)
    schedule = build_amortization_schedule(principal, apr, term, first_due)

    today = date.today()
    elapsed_months = min(term, max(0, (today - funded_at.date()).days // 30))
    missed_months = min(elapsed_months, max(0, delinquent_days // 30 + (1 if delinquent_days % 30 else 0)))
    paid_count = max(0, elapsed_months - missed_months)

    for i, row in enumerate(schedule):
        if i < paid_count:
            row["status"] = "paid"
        elif i < paid_count + missed_months:
            row["status"] = "missed"
        # else: stays "scheduled" (set by build_amortization_schedule)

    outstanding = principal - sum((Decimal(str(row["principal"])) for row in schedule[:paid_count]), Decimal("0"))
    days_past_due = 0
    if paid_count < elapsed_months:
        oldest_missed_due = date.fromisoformat(schedule[paid_count]["due_date"])
        days_past_due = max(0, (today - oldest_missed_due).days)

    next_idx = paid_count + missed_months
    next_due = date.fromisoformat(schedule[next_idx]["due_date"]) if next_idx < len(schedule) else None
    last_payment = schedule[paid_count - 1] if paid_count > 0 else None

    if days_past_due <= 0:
        status = ServicingStatus.CURRENT.value
    elif days_past_due >= 90:
        status = ServicingStatus.DEFAULT.value
    else:
        status = ServicingStatus.DELINQUENT.value

    loan = ServicedLoan(
        id=new_id(), tenant_id=tenant, application_id=app_id,
        loan_number=num, product=product, borrower_name=name,
        principal=principal, outstanding_principal=outstanding.quantize(Decimal("0.01")),
        apr=apr, term_months=term, monthly_payment=Decimal(str(schedule[0]["amount"])),
        next_due_date=next_due,
        last_payment_date=date.fromisoformat(last_payment["due_date"]) if last_payment else None,
        last_payment_amount=Decimal(str(last_payment["amount"])) if last_payment else None,
        payments_made=paid_count, days_past_due=days_past_due, status=status,
        payment_schedule=schedule, funded_at=funded_at,
    )
    return loan, days_past_due


def _contact(days_ago, hour_local, channel, notes):
    """A past FDCPA-compliant collection contact log entry (within the
    8am-9pm window by construction, since it already happened)."""
    at = _ago(days_ago).replace(hour=hour_local, minute=0, second=0, microsecond=0)
    return {"at": at.isoformat(), "hour_local": hour_local, "channel": channel,
            "harassment": False, "notes": notes, "actor": "collections_agent"}


async def _seed_servicing(db, tenant):
    """Fund the approved applications selected in _SERVICING and open FDCPA-
    governed collections cases on the delinquent ones. Independently idempotent:
    guarded on a ServicedLoan sentinel (NOT LoanApplication) so a tenant seeded
    before this wave still backfills servicing. Application ids come from the DB
    so it works whether the apps were just created or already existed. The
    caller commits."""
    existing_loans = (await db.execute(
        select(sqlfunc.count()).select_from(ServicedLoan)
        .where(ServicedLoan.tenant_id == tenant))).scalar() or 0
    if existing_loans:
        return

    app_ids_by_number = {num: aid for num, aid in (await db.execute(
        select(LoanApplication.application_number, LoanApplication.id)
        .where(LoanApplication.tenant_id == tenant))).all()}

    apps_by_number = {row[0]: row for row in _APPS}
    loans_by_number: dict[str, tuple] = {}
    for num, delinquent_days in _SERVICING.items():
        (_n, name, product, amount, term, score, _income, _dti, _pclass,
         decided_ago) = apps_by_number[num]
        loan, dpd = _fund_loan(tenant, app_ids_by_number[num], num, name, product, amount,
                               term, score, decided_ago, delinquent_days)
        db.add(loan)
        loans_by_number[num] = (loan, dpd)

    # Persist the serviced loans before the collection cases reference them
    # (Postgres enforces the serviced_loan_id FK; SQLite defers it).
    await db.flush()

    # LN-1002: 30-59-day DPD bucket, an open collections case with a short
    # contact history - validation notice mailed, one call, one follow-up.
    loan_1002, dpd_1002 = loans_by_number["LN-1002"]
    db.add(CollectionCase(
        id=new_id(), tenant_id=tenant, serviced_loan_id=loan_1002.id,
        status=CollectionCaseStatus.IN_PROGRESS.value,
        delinquency_bucket=delinquency_bucket(dpd_1002),
        validation_notice_sent=True, validation_notice_sent_at=_ago(14),
        contact_log=[
            _contact(14, 9, "mail", "FDCPA validation notice mailed."),
            _contact(9, 11, "phone",
                    "Outbound call - borrower acknowledged the missed payment and "
                    "promised to pay within the week."),
            _contact(3, 15, "phone",
                    "Follow-up call - no answer, left a voicemail requesting a callback."),
        ],
        last_contact_at=_ago(3), opened_at=_ago(15),
    ))

    # LN-1005: 90+ bucket, escalated - a longer contact history spanning
    # several weeks, every contact inside the 8am-9pm FDCPA window.
    loan_1005, dpd_1005 = loans_by_number["LN-1005"]
    db.add(CollectionCase(
        id=new_id(), tenant_id=tenant, serviced_loan_id=loan_1005.id,
        status=CollectionCaseStatus.ESCALATED.value,
        delinquency_bucket=delinquency_bucket(dpd_1005),
        validation_notice_sent=True, validation_notice_sent_at=_ago(63),
        contact_log=[
            _contact(64, 9, "mail", "FDCPA validation notice mailed."),
            _contact(58, 10, "phone", "Outbound call - borrower requested a hardship review."),
            _contact(45, 14, "phone",
                    "Follow-up call - borrower disputed the amount; dispute logged."),
            _contact(30, 11, "phone", "Outbound call - no answer, left a voicemail."),
            _contact(16, 16, "phone",
                    "Outbound call - borrower proposed a partial-payment plan."),
            _contact(4, 13, "phone", "Follow-up call confirming the partial-payment plan terms."),
        ],
        last_contact_at=_ago(4), opened_at=_ago(65),
    ))

    logger.info(f"   - {len(loans_by_number)} serviced loans, 2 collection cases "
                f"(FDCPA-governed contact log)")


async def seed_tenant(db, tenant: str) -> bool:
    # A second run must not duplicate rows or crash on the application_number
    # unique constraint.
    # REVIEW: lending is the ONE department whose "already seeded" branch is not
    # a pure no-op - it still backfills servicing/collections, because those were
    # added in a later wave and tenants seeded before it have applications but no
    # ServicedLoan rows. Reproduced exactly (backfill, commit, return False).
    # Fix, if this is unwanted: move the backfill to a migration and make the
    # skip branch a plain `return False` like the other nine. Behaviour change -
    # deliberately NOT made here.
    if await already_seeded(db, "Lending", LoanApplication, tenant):
        await _seed_servicing(db, tenant)
        await db.commit()
        return False

    for product, p in _POLICIES.items():
        db.add(CreditPolicy(id=new_id(), tenant_id=tenant, product=product,
                            is_active=True, **p))

    approvals = denials = pending = 0
    for (num, name, product, amount, term, score, income, dti, pclass, decided_ago) in _APPS:
        app_id = new_id()
        if decided_ago is None:
            status = LoanStatus.RECEIVED.value
        else:
            decision, reasons = _decide(product, amount, score, income, dti)
            status = LoanStatus.APPROVED.value if decision == "APPROVE" else LoanStatus.DENIED.value
        db.add(LoanApplication(
            id=app_id, tenant_id=tenant, application_number=num, applicant_name=name,
            product=product, credit_purpose="business" if product == "small_business" else "consumer",
            amount=Decimal(str(amount)), term_months=term, credit_score=score,
            annual_income=Decimal(str(income)), dti_ratio=Decimal(str(dti)),
            monthly_debt=Decimal(str(round(income * dti / 12, 2))),
            protected_class=pclass, status=status,
            intake_score=Decimal(str(round(min(1.0, score / 850), 4)))))

        if decided_ago is None:
            pending += 1
            continue

        dec_id = new_id()
        apr = _apr(product, score)
        if decision == "APPROVE":
            approvals += 1
            fin_charge = round(amount * (apr / 100) * (term / 12), 2)
            db.add(UnderwritingDecision(
                id=dec_id, tenant_id=tenant, application_id=app_id, decision="APPROVE",
                reasons=["Meets credit-score, DTI, income and program-limit policy"],
                confidence=Decimal("0.92"), decided_by="underwriter_agent",
                decided_at=_ago(decided_ago), gate_status="SUCCESS_CLEAN",
                apr=Decimal(str(apr)), finance_charge=Decimal(str(fin_charge)),
                amount_financed=Decimal(str(amount)),
                total_of_payments=Decimal(str(round(amount + fin_charge, 2)))))
        else:
            denials += 1
            db.add(UnderwritingDecision(
                id=dec_id, tenant_id=tenant, application_id=app_id, decision="DENY",
                reasons=reasons, confidence=Decimal("0.95"), decided_by="underwriter_agent",
                decided_at=_ago(decided_ago), gate_status="SUCCESS_CLEAN"))
            # Persist the application + decision before the notice references
            # them: on Postgres the FK is enforced, so the parent rows must
            # exist first (SQLite defers FK checks, which hid this).
            await db.flush()
            db.add(AdverseActionNotice(
                id=new_id(), tenant_id=tenant, application_id=app_id, decision_id=dec_id,
                specific_reasons=reasons,
                body=("We are unable to approve your application at this time for the "
                      "following principal reason(s): " + "; ".join(reasons) +
                      ". You have the right to a free copy of your credit report and to "
                      "dispute its accuracy. (ECOA / Reg B, 12 CFR 1002.9)"),
                decision_date=date.today() - timedelta(days=decided_ago),
                sent_at=_ago(decided_ago - 1 if decided_ago > 1 else 0),
                within_30_days=True))

    # Servicing + collections (independently idempotent - see _seed_servicing).
    await _seed_servicing(db, tenant)

    await db.commit()
    logger.info("[SUCCESS] Seeded Lending database:")
    logger.info(f"   - {len(_APPS)} applications ({approvals} approved, {denials} denied, "
                f"{pending} in intake), {len(_POLICIES)} credit policies, "
                f"{denials} adverse-action notices")
    return True


async def seed(tenant: str | None = None) -> bool:
    return await run_standalone(async_engine, AsyncSessionLocal, seed_tenant, tenant or TENANT)


if __name__ == "__main__":
    asyncio.run(seed())
