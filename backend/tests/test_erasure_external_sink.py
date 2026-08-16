"""Erasure completeness — DR-safe external journal + support/procurement/legal reach.

Two guards that FAIL if the fixes regress:
  * an erasure recorded ONLY in the external file sink (the DB journal row gone, as
    after a restore) still drives a replay that re-erases the resurrected PII;
  * a CUSTOMER's support ticket description and comment body are anonymised, while
    an agent's comment on the same ticket is left intact.
"""
import pytest
from sqlalchemy import select

from app.services.privacy_erasure import erase_subject, replay_deletions_from_external
from app.services import deletion_sink
from app.hr.models.core import HREmployee
from app.finance.models.accounts_receivable import Customer
from app.support.models.tickets import Ticket, TicketComment
from app.models.settings import DeletionJournal
from datetime import date

TENANT = "tenant_acme"


# ── (1) external sink drives replay when the DB journal row is absent ──────────

@pytest.mark.asyncio
async def test_external_sink_replays_without_db_journal(db, tmp_path, monkeypatch):
    monkeypatch.setenv("KAEOS_DELETION_JOURNAL_PATH", str(tmp_path / "ext.log"))

    emp = HREmployee(
        tenant_id=TENANT, first_name="Rosalind", last_name="Franklin",
        email="ros@example.com", hire_date=date(2020, 1, 1), job_title="Scientist",
    )
    db.add(emp)
    await db.commit()
    emp_id = emp.id

    await erase_subject(db, TENANT, employee_id=emp_id)

    # The external sink captured the entry (PII-free, with the employee id).
    ext = deletion_sink.read_all()
    assert any(e["employee_id"] == emp_id and e["operation"] == "ERASE_SUBJECT"
               for e in ext), ext

    # Simulate a restore: the DB journal table is wiped AND the PII reappears.
    await db.execute(DeletionJournal.__table__.delete())
    await db.commit()
    db.expire_all()
    row = (await db.execute(select(HREmployee).where(HREmployee.id == emp_id))).scalar_one()
    row.first_name, row.last_name, row.email = "Rosalind", "Franklin", "ros@example.com"
    await db.commit()

    # Replay from the EXTERNAL sink (the DB journal knows nothing now).
    result = await replay_deletions_from_external(db, tenant_id=TENANT)
    assert result["replayed"] >= 1, result

    db.expire_all()
    row2 = (await db.execute(select(HREmployee).where(HREmployee.id == emp_id))).scalar_one()
    assert row2.first_name == "[ERASED]", "external-sink replay must re-erase restored PII"


# ── (2) customer support ticket content is anonymised ─────────────────────────

@pytest.mark.asyncio
async def test_erase_subject_nulls_support_ticket_body(db, tmp_path, monkeypatch):
    monkeypatch.setenv("KAEOS_DELETION_JOURNAL_PATH", str(tmp_path / "ext.log"))

    cust = Customer(
        tenant_id=TENANT, customer_code="C1", name="Alan Turing",
        email="alan@example.com",
    )
    db.add(cust)
    await db.commit()
    cust_id = cust.id

    tkt = Ticket(
        tenant_id=TENANT, ticket_number="T-1", customer_id=cust_id,
        subject="Card declined",
        description="My card 4111 1111 1111 1111 was declined, SSN 123-45-6789",
    )
    db.add(tkt)
    await db.commit()
    tkt_id = tkt.id

    cust_comment = TicketComment(
        tenant_id=TENANT, ticket_id=tkt_id, author_type="CUSTOMER",
        body="Here is my full card number again: 4111 1111 1111 1111",
    )
    agent_comment = TicketComment(
        tenant_id=TENANT, ticket_id=tkt_id, author_type="AGENT",
        body="Thanks, escalating to billing.",
    )
    db.add_all([cust_comment, agent_comment])
    await db.commit()
    cust_cid, agent_cid = cust_comment.id, agent_comment.id

    await erase_subject(db, TENANT, email="alan@example.com")

    db.expire_all()
    t2 = (await db.execute(select(Ticket).where(Ticket.id == tkt_id))).scalar_one()
    assert t2.description == "[ERASED]", "customer ticket description must be anonymised"

    cc = (await db.execute(select(TicketComment).where(TicketComment.id == cust_cid))).scalar_one()
    ac = (await db.execute(select(TicketComment).where(TicketComment.id == agent_cid))).scalar_one()
    assert cc.body == "[ERASED]", "customer comment body must be anonymised"
    assert ac.body == "Thanks, escalating to billing.", "agent comment is not the subject's PII"
