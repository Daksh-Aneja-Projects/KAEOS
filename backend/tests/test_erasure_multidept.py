"""§05 GDPR erasure — multi-department coverage.

Prior erasure tests exercised only HR (+ lending). This proves ``erase_subject``
reaches the sales / finance / healthcare direct-identifier tables too:
  * sls_contacts   — email-keyed person identifiers (name/email/phone)
  * fin_customers  — email-keyed customer master (email/phone/tax_id/primary_contact)
  * fin_vendors    — email-keyed vendor master (email/tax_id/bank details)
  * hlth_encounters — patient_ref-keyed PHI (patient_ref tombstone + reason null)

Runs on the in-memory unit harness (no live server, no LLM).
"""
import pytest
from sqlalchemy import select

from app.services.privacy_erasure import erase_subject

TENANT = "tenant_acme"
EMAIL = "jordan.rivers@example.com"
PATIENT_REF = "PT-ERASE-001"


@pytest.mark.asyncio
async def test_erase_subject_reaches_sales_finance_healthcare(db):
    from app.sales.models.accounts import Account, Contact
    from app.finance.models.accounts_receivable import Customer
    from app.finance.models.accounts_payable import Vendor
    from app.healthcare.models.core import PatientEncounter

    acct = Account(tenant_id=TENANT, name="Rivers Holdings")
    db.add(acct)
    await db.commit()
    await db.refresh(acct)

    contact = Contact(
        tenant_id=TENANT, account_id=acct.id, first_name="Jordan", last_name="Rivers",
        email=EMAIL, phone="+1-555-0101", title="Buyer",
    )
    customer = Customer(
        tenant_id=TENANT, customer_code="CST-ER1", name="Rivers Retail",
        tax_id="TAX-CUST-9", primary_contact="Jordan Rivers", email=EMAIL, phone="+1-555-0102",
    )
    vendor = Vendor(
        tenant_id=TENANT, vendor_code="VEN-ER1", name="Rivers Supply",
        tax_id="TAX-VEND-9", primary_contact="Jordan Rivers", email=EMAIL, phone="+1-555-0103",
        bank_account_number="000123456789", bank_routing_number="021000021",
    )
    encounter = PatientEncounter(
        tenant_id=TENANT, encounter_number="ENC-ER1", patient_ref=PATIENT_REF,
        encounter_type="office_visit", status="OPEN", reason="chest pain, rule out MI",
    )
    db.add_all([contact, customer, vendor, encounter])
    await db.commit()
    contact_id, customer_id, vendor_id, enc_id = (
        contact.id, customer.id, vendor.id, encounter.id,
    )

    # email keys sales/finance; subject_ref keys healthcare (patient_ref).
    receipt = await erase_subject(db, TENANT, email=EMAIL, subject_ref=PATIENT_REF)

    tables = receipt["tables"]
    for tname in ("sls_contacts", "fin_customers", "fin_vendors", "hlth_encounters"):
        assert tables.get(tname, 0) >= 1, f"{tname} not erased: {tables}"

    # Core UPDATEs bypass the identity map; expire so re-reads hit the DB.
    db.expire_all()

    c = (await db.execute(select(Contact).where(Contact.id == contact_id))).scalar_one()
    assert c.first_name == "[ERASED]" and c.last_name == "[ERASED]"
    assert c.email != EMAIL and "invalid.example" in c.email
    assert c.phone is None

    cust = (await db.execute(select(Customer).where(Customer.id == customer_id))).scalar_one()
    assert cust.email != EMAIL and "invalid.example" in cust.email
    assert cust.phone is None and cust.tax_id is None and cust.primary_contact is None

    ven = (await db.execute(select(Vendor).where(Vendor.id == vendor_id))).scalar_one()
    assert ven.email != EMAIL and "invalid.example" in ven.email
    assert ven.tax_id is None and ven.phone is None and ven.primary_contact is None
    assert ven.bank_account_number is None and ven.bank_routing_number is None

    enc = (await db.execute(
        select(PatientEncounter).where(PatientEncounter.id == enc_id)
    )).scalar_one()
    assert enc.patient_ref == "[ERASED]"   # NOT NULL, so tombstoned not nulled
    assert enc.reason is None
