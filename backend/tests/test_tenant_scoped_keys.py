"""Tenant-scoped business keys (review P0.5): two tenants may share an
invoice number / skill name; ONE tenant may not duplicate it."""
import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.domain import Skill


def _skill(tenant, name):
    return Skill(id=str(uuid.uuid4()), skill_id=name, tenant_id=tenant,
                 department="finance", status="ACTIVE", confidence=0.9)


async def test_two_tenants_may_share_a_skill_name(db):
    db.add(_skill("tenant_a", "vendor_payment_approval"))
    db.add(_skill("tenant_b", "vendor_payment_approval"))
    await db.commit()  # would IntegrityError under the old global unique


async def test_one_tenant_may_not_duplicate_a_skill_name(db):
    db.add(_skill("tenant_c", "vendor_payment_approval"))
    await db.commit()
    db.add(_skill("tenant_c", "vendor_payment_approval"))
    with pytest.raises(IntegrityError):
        await db.commit()
    await db.rollback()


async def test_two_tenants_may_share_an_invoice_number(db):
    from datetime import date

    from app.finance.models.accounts_receivable import Customer, CustomerInvoice

    for t in ("tenant_a", "tenant_b"):
        cust = Customer(id=f"c-{t}", tenant_id=t, name="Acme",
                        customer_code=f"CUST-{t}")
        db.add(cust)
        db.add(CustomerInvoice(
            id=f"i-{t}", tenant_id=t, customer_id=cust.id,
            invoice_number="INV-001", invoice_date=date(2026, 8, 1),
            due_date=date(2026, 9, 1), subtotal=100, total_amount=100,
            balance_due=100))
    await db.commit()
