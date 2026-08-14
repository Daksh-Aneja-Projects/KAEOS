"""
KAEOS Lending Domain - Seed Script

A handful of demo loan applications + a credit policy for tenant_acme, shaped so
the underwriter produces a genuine APPROVE and a genuine DENY, and so the
fair-lending analysis has protected-class data to work with.
"""
import asyncio
import uuid

from app.core.database import AsyncSessionLocal, async_engine
from app.lending.models.core import CreditPolicy, LoanApplication, LoanStatus
from app.models.domain import Base

TENANT = "tenant_acme"


def _id():
    return str(uuid.uuid4())


_APPS = [
    # Clean approve.
    dict(application_number="LN-1001", applicant_name="Jordan Rivera",
         amount=18000, credit_score=742, annual_income=96000, dti_ratio=0.28,
         protected_class={"gender": "female", "ethnicity": "hispanic"}),
    # Clean approve.
    dict(application_number="LN-1002", applicant_name="Sam Okafor",
         amount=25000, credit_score=705, annual_income=120000, dti_ratio=0.31,
         protected_class={"gender": "male", "ethnicity": "black"}),
    # Denial: score + DTI.
    dict(application_number="LN-1003", applicant_name="Alex Chen",
         amount=32000, credit_score=598, annual_income=41000, dti_ratio=0.58,
         protected_class={"gender": "male", "ethnicity": "asian"}),
    # Denial: amount over cap.
    dict(application_number="LN-1004", applicant_name="Priya Nair",
         amount=75000, credit_score=760, annual_income=210000, dti_ratio=0.22,
         protected_class={"gender": "female", "ethnicity": "asian"}),
]


async def seed():
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as db:
        db.add(CreditPolicy(
            id=_id(), tenant_id=TENANT, product="personal_loan",
            min_credit_score=640, max_dti_ratio=0.45, min_annual_income=24000,
            max_amount=50000, base_apr=12.5, is_active=True))
        for a in _APPS:
            db.add(LoanApplication(
                id=_id(), tenant_id=TENANT, product="personal_loan",
                credit_purpose="consumer", status=LoanStatus.RECEIVED.value, **a))
        await db.commit()
    print(f"[lending.seed] seeded {len(_APPS)} applications + 1 credit policy for {TENANT}")


if __name__ == "__main__":
    asyncio.run(seed())
