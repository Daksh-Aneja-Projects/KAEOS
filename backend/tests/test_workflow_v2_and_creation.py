"""
Sprint-2 backend tests: entity creation endpoints, workflow guards,
per-state role floors, and the cross-domain Org Pulse aggregation.
"""
from datetime import date

import pytest
from fastapi import HTTPException
from httpx import AsyncClient

TENANT = "tenant_acme"


# ── Entity creation ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_ticket_then_transition(async_client: AsyncClient):
    r = await async_client.post("/api/v1/support/tickets", json={
        "subject": "VPN keeps dropping",
        "description": "Drops every 20 minutes on the Berlin office network.",
        "priority": "HIGH",
    })
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "NEW"
    assert body["number"].startswith("T-")

    r2 = await async_client.post(f"/api/v1/support/tickets/{body['id']}/transition",
                                 json={"to_state": "OPEN"})
    assert r2.status_code == 200, r2.text


@pytest.mark.asyncio
async def test_create_opportunity_and_incident(async_client: AsyncClient):
    r = await async_client.post("/api/v1/sales/opportunities", json={
        "name": "Initech expansion", "amount": 42000, "probability": 30,
    })
    assert r.status_code == 201, r.text
    assert r.json()["stage"] == "PROSPECTING"

    r = await async_client.post("/api/v1/engineering/incidents", json={
        "title": "Elevated 5xx on checkout", "severity": "SEV2",
        "customer_impacting": True, "affected_users": 1200,
    })
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "DETECTED"
    assert body["number"].startswith("INC-")


@pytest.mark.asyncio
async def test_create_time_off_requires_real_employee(async_client: AsyncClient, db):
    r = await async_client.post("/api/v1/hr/time-off-requests", json={
        "employee_id": "ghost-employee", "leave_type": "PTO",
        "start_date": "2026-08-03", "end_date": "2026-08-07",
        "hours_requested": 40,
    })
    assert r.status_code == 404

    from app.hr.models.core import HREmployee
    emp = HREmployee(tenant_id=TENANT, first_name="Grace", last_name="Hopper",
                     email="grace@acme.test", hire_date=date(2024, 1, 8),
                     job_title="Rear Admiral of Engineering")
    db.add(emp)
    await db.commit()
    await db.refresh(emp)

    r = await async_client.post("/api/v1/hr/time-off-requests", json={
        "employee_id": emp.id, "leave_type": "PTO",
        "start_date": "2026-08-03", "end_date": "2026-08-07",
        "hours_requested": 40,
    })
    assert r.status_code == 201, r.text
    req_id = r.json()["id"]

    r = await async_client.post(f"/api/v1/hr/time-off-requests/{req_id}/transition",
                                json={"to_state": "APPROVED"})
    assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_create_expense_report_lifecycle(async_client: AsyncClient):
    r = await async_client.post("/api/v1/finance/expense-reports", json={
        "title": "Q3 client visit", "employee_id": "emp-1", "total_amount": 950.50,
    })
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "DRAFT"
    assert body["number"].startswith("EXP-")

    r = await async_client.post(f"/api/v1/finance/expense-reports/{body['id']}/transition",
                                json={"to_state": "SUBMITTED"})
    assert r.status_code == 200, r.text


# ── Guards & role floors ─────────────────────────────────────────────────

async def _seed_invoice(db, **overrides):
    from app.finance.models.accounts_payable import Invoice, InvoiceStatus, Vendor, VendorStatus
    v = Vendor(tenant_id=TENANT, vendor_code=f"V-{overrides.get('invoice_number','X')}",
               name="Duplicheck Ltd", status=VendorStatus.ACTIVE)
    db.add(v)
    await db.commit()
    inv = Invoice(
        tenant_id=TENANT, vendor_id=v.id,
        invoice_number=overrides.get("invoice_number", "INV-G1"),
        invoice_date=date(2026, 7, 1), due_date=date(2026, 8, 1),
        status=InvoiceStatus.APPROVED, subtotal=100, total_amount=100,
        balance_due=100, ai_duplicate_flag=overrides.get("dup", False),
    )
    db.add(inv)
    await db.commit()
    await db.refresh(inv)
    return inv


@pytest.mark.asyncio
async def test_duplicate_flagged_invoice_cannot_be_paid(async_client: AsyncClient, db):
    inv = await _seed_invoice(db, invoice_number="INV-DUP", dup=True)
    r = await async_client.post(f"/api/v1/finance/invoices/{inv.id}/transition",
                                json={"to_state": "PAID"})
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["error"] == "guard_blocked"

    # Clean invoice pays fine.
    ok = await _seed_invoice(db, invoice_number="INV-OK")
    r = await async_client.post(f"/api/v1/finance/invoices/{ok.id}/transition",
                                json={"to_state": "PAID"})
    assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_void_requires_admin_role(db):
    """Role floor is enforced by the engine, not just the endpoint gate."""
    from app.core.workflow import apply_transition
    from app.finance.services.workflows import INVOICE_WORKFLOW

    inv = await _seed_invoice(db, invoice_number="INV-VOID")
    operator = {"tenant_id": TENANT, "role": "operator", "name": "op"}
    with pytest.raises(HTTPException) as exc:
        await apply_transition(db, INVOICE_WORKFLOW, inv.id, "VOIDED", operator)
    assert exc.value.status_code == 403
    assert exc.value.detail["error"] == "role_required"

    admin = {"tenant_id": TENANT, "role": "admin", "name": "boss"}
    result = await apply_transition(db, INVOICE_WORKFLOW, inv.id, "VOIDED", admin)
    assert result["to_state"] == "VOIDED"


@pytest.mark.asyncio
async def test_large_expense_needs_admin(db):
    from app.core.workflow import apply_transition
    from app.finance.models.expense import ExpenseReport, ExpenseReportStatus
    from app.finance.services.workflows import EXPENSE_REPORT_WORKFLOW

    rep = ExpenseReport(tenant_id=TENANT, report_number="EXP-BIG",
                        title="Conference sponsorship", employee_id="emp-1",
                        status=ExpenseReportStatus.PENDING_APPROVAL,
                        total_amount=25_000)
    db.add(rep)
    await db.commit()
    await db.refresh(rep)

    operator = {"tenant_id": TENANT, "role": "operator", "name": "op"}
    with pytest.raises(HTTPException) as exc:
        await apply_transition(db, EXPENSE_REPORT_WORKFLOW, rep.id, "APPROVED", operator)
    assert exc.value.status_code == 409
    assert exc.value.detail["error"] == "guard_blocked"

    admin = {"tenant_id": TENANT, "role": "admin", "name": "boss"}
    result = await apply_transition(db, EXPENSE_REPORT_WORKFLOW, rep.id, "APPROVED", admin)
    assert result["to_state"] == "APPROVED"


@pytest.mark.asyncio
async def test_zero_dollar_deal_cannot_close_won(async_client: AsyncClient, db):
    from app.sales.models.pipeline import Opportunity, OpportunityStage
    opp = Opportunity(tenant_id=TENANT, name="Freebie", amount=0,
                      stage=OpportunityStage.NEGOTIATION)
    db.add(opp)
    await db.commit()
    await db.refresh(opp)
    r = await async_client.post(f"/api/v1/sales/opportunities/{opp.id}/transition",
                                json={"to_state": "CLOSED_WON"})
    assert r.status_code == 409
    assert r.json()["detail"]["error"] == "guard_blocked"


# ── Org Pulse ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_org_pulse_shape_and_health(async_client: AsyncClient):
    r = await async_client.get("/api/v1/org/pulse")
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"org_health", "domains", "insights"}
    assert len(body["domains"]) == 7
    names = {d["domain"] for d in body["domains"]}
    assert names == {"finance", "hr", "sales", "support", "operations", "legal", "engineering"}
    for d in body["domains"]:
        assert 0 <= d["health"] <= 100


@pytest.mark.asyncio
async def test_org_activity_streams_transitions(async_client: AsyncClient):
    r = await async_client.post("/api/v1/support/tickets", json={
        "subject": "Pulse probe", "description": "x", "priority": "LOW",
    })
    tid = r.json()["id"]
    await async_client.post(f"/api/v1/support/tickets/{tid}/transition",
                            json={"to_state": "OPEN"})

    r = await async_client.get("/api/v1/org/activity")
    assert r.status_code == 200
    events = r.json()
    assert any(e["entity_id"] == tid and e["to_state"] == "OPEN" for e in events)
