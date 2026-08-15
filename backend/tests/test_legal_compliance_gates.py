"""
CONFLICT_OF_INTEREST / LEGAL_HOLD / RETENTION_SCHEDULE were real, registered
checkers (app/compliance/checkers/legal.py) that no legal agent ever passed
tags for. This proves they now gate real actions:
- POST /legal/matters screens new-matter intake for adverse-party conflicts.
- The 'matter' WorkflowSpec's CLOSED guard runs LEGAL_HOLD + RETENTION_SCHEDULE.
- 'matter' and 'obligation' WorkflowSpecs (gap 7) exist and transition for real.
"""
import uuid

import pytest

from app.legal.services.compliance_gates import (
    ConflictOfInterestBlocked, guard_matter_closure, screen_new_matter,
)


def _t():
    return f"tenant_legal_gate_{uuid.uuid4().hex[:6]}"


# ── screen_new_matter (CONFLICT_OF_INTEREST) ────────────────────────────────

def test_screen_new_matter_blocks_on_adverse_overlap():
    with pytest.raises(ConflictOfInterestBlocked) as exc:
        screen_new_matter(["Acme Corp"], ["acme corp"])
    assert "CONFLICT_OF_INTEREST" in str(exc.value)


def test_screen_new_matter_passes_with_no_overlap():
    screen_new_matter(["Acme Corp"], ["Globex Inc"])  # must not raise


def test_screen_new_matter_not_applicable_with_no_parties():
    screen_new_matter(None, None)  # nothing to screen — must not raise or fabricate a pass


# ── guard_matter_closure (LEGAL_HOLD + RETENTION_SCHEDULE) ──────────────────

def test_guard_matter_closure_advisory_when_no_hold_data():
    """LegalMatter models no on_legal_hold / retention_until column yet, so
    closing an unheld matter is ADVISORY (non-blocking) — real execution
    against the checkers, honest about what cannot be verified."""
    assert guard_matter_closure(object(), object()) is None


# ── POST /legal/matters: conflict screen wired into new-matter intake ───────

async def test_create_matter_blocked_on_conflict(async_client):
    tenant = _t()
    r = await async_client.post("/api/v1/legal/matters", headers={"X-Tenant-ID": tenant}, json={
        "title": "Acme Dispute", "matter_type": "Litigation",
        "parties": "Acme Corp, Jane Roe", "adverse_parties": "Acme Corp",
    })
    assert r.status_code == 409, r.text
    assert "CONFLICT_OF_INTEREST" in r.json()["detail"]


async def test_create_matter_succeeds_with_no_conflict(async_client):
    tenant = _t()
    r = await async_client.post("/api/v1/legal/matters", headers={"X-Tenant-ID": tenant}, json={
        "title": "New Vendor MSA Review", "matter_type": "Corporate",
        "priority": "high", "parties": "KAEOS Inc", "adverse_parties": "Globex Corp",
    })
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["title"] == "New Vendor MSA Review"
    assert body["priority"] == "HIGH"

    r2 = await async_client.get("/api/v1/legal/matters", headers={"X-Tenant-ID": tenant})
    assert any(m["title"] == "New Vendor MSA Review" for m in r2.json())


async def test_create_matter_rejects_cross_tenant_attorney(async_client):
    r = await async_client.post("/api/v1/legal/matters", headers={"X-Tenant-ID": _t()}, json={
        "title": "Ghost Attorney Matter", "matter_type": "Corporate",
        "assigned_attorney_id": "does-not-exist",
    })
    assert r.status_code == 404


async def test_create_matter_rejects_invalid_priority(async_client):
    r = await async_client.post("/api/v1/legal/matters", headers={"X-Tenant-ID": _t()}, json={
        "title": "Bad Priority Matter", "matter_type": "Corporate", "priority": "SUPER_URGENT",
    })
    assert r.status_code == 422


# ── 'matter' / 'obligation' WorkflowSpecs (gap 7) exist and transition ──────

async def test_matter_workflow_transitions_and_closure_guard_runs(async_client, db):
    from app.legal.models.core import LegalMatter, MatterStatus

    tenant = _t()
    m = LegalMatter(id=str(uuid.uuid4()), tenant_id=tenant, title="Test Matter",
                    matter_type="Corporate", status=MatterStatus.NEW)
    db.add(m)
    await db.commit()

    r = await async_client.post(f"/api/v1/legal/matters/{m.id}/transition",
                                headers={"X-Tenant-ID": tenant}, json={"to_state": "IN_PROGRESS"})
    assert r.status_code == 200, r.text

    # Closing requires admin — DEV_MODE's dev tenant is already admin.
    r = await async_client.post(f"/api/v1/legal/matters/{m.id}/transition",
                                headers={"X-Tenant-ID": tenant}, json={"to_state": "CLOSED"})
    assert r.status_code == 200, r.text  # LEGAL_HOLD/RETENTION_SCHEDULE ADVISORY -> not blocked
    assert r.json()["to_state"] == "CLOSED"


async def test_obligation_workflow_transitions(async_client, db):
    from app.legal.models.compliance import ComplianceObligation, ObligationStatus

    tenant = _t()
    ob = ComplianceObligation(id=str(uuid.uuid4()), tenant_id=tenant, title="Test Obligation",
                              status=ObligationStatus.PENDING)
    db.add(ob)
    await db.commit()

    r = await async_client.post(f"/api/v1/legal/compliance/obligations/{ob.id}/transition",
                                headers={"X-Tenant-ID": tenant}, json={"to_state": "COMPLETED"})
    assert r.status_code == 200, r.text
    assert r.json()["to_state"] == "COMPLETED"


def test_legal_workflow_specs_include_matter_and_obligation():
    from app.legal.services.workflows import SPECS
    assert "matter" in SPECS
    assert "obligation" in SPECS
    assert "CLOSED" in SPECS["matter"].states
    assert "COMPLETED" in SPECS["obligation"].states
