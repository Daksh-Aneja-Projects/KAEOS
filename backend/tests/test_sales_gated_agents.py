"""Sales gated-agent tests.

Two CRIT fixes proven here:

1. run_gated_sales_skill no longer hardcodes data_processing_basis_logged=True
   with no legal_basis fact behind it. Every GDPR-tagged gated sales agent
   (lead scoring, account health, churn, pipeline coach, forecast, proposal
   gen) used to reach Gate 6 and unconditionally return FAILED_AUDIT instead
   of a real decision (app/sales/agents/gated_runner.py).
2. CPQAgent.evaluate_quote now routes through run_gated_sales_skill (SOX
   tagged) instead of calling the LLM router directly, so discount/margin
   decisions get the same compliance + confidence + HITL + audit treatment as
   every other sales and finance money-touching agent
   (app/sales/agents/cpq_agent.py).

Also covers: the seed idempotency guard + full funnel-stage coverage
(app/sales/seed.py), GET /sales/commission joining plan_name, and the
CCPA/TCPA/DSAR privacy-gate call sites (app/sales/services/privacy.py).
"""
import json
import socket
import uuid

import pytest
from sqlalchemy import select

from app.sales.agents.cpq_agent import CPQAgent
from app.sales.agents.gated_runner import run_gated_sales_skill
from app.sales.models.leads import Lead, LeadSource
from app.sales.models.pipeline import Opportunity, OpportunityStage
from app.sales.services.privacy import (
    PrivacyCheckBlocked, check_contact, check_data_sale, check_dsar,
)
from app.services.compliance import ComplianceEngine


def _t():
    return f"tenant_sales_{uuid.uuid4().hex[:6]}"


def _ollama_reachable() -> bool:
    try:
        with socket.create_connection(("localhost", 11434), timeout=2):
            return True
    except OSError:
        return False


# ── The exact bug, reproduced and fixed at the unit level ──────────────────

def test_enforce_audit_requirements_rejects_flag_without_real_basis():
    """The bug: a hardcoded True with no legal_basis fact must NOT satisfy the
    GDPR/HIPAA/CCPA post-execution audit requirement."""
    engine = ComplianceEngine()
    assert engine.enforce_audit_requirements(
        ["GDPR"], {"data_processing_basis_logged": True}
    ) is False


def test_enforce_audit_requirements_passes_with_real_basis():
    engine = ComplianceEngine()
    assert engine.enforce_audit_requirements(
        ["GDPR"],
        {"data_processing_basis_logged": True, "legal_basis": "contract:x"},
    ) is True


# ── gated_runner.py derives the audit flag from context, never hardcodes it ─

async def test_run_gated_sales_skill_derives_audit_flag_from_legal_basis(monkeypatch):
    captured = {}

    async def fake_execute_skill(self, skill, ctx):
        captured.update(ctx)
        return {"status": "SUCCESS_CLEAN", "reasoning_chain": []}

    from app.agents.runtime import AgentExecutor
    monkeypatch.setattr(AgentExecutor, "execute_skill", fake_execute_skill)

    result = await run_gated_sales_skill(
        skill_id="sales_lead_scoring", steps=[{"step": 1, "prompt": "x"}],
        context={"lead_id": "abc", "legal_basis": "legitimate_interests:sales_lead_qualification"},
        tenant_id=_t(),
    )
    assert captured["legal_basis"] == "legitimate_interests:sales_lead_qualification"
    assert captured["data_processing_basis_logged"] is True
    assert result["status"] == "SUCCESS_CLEAN"


async def test_run_gated_sales_skill_flag_honest_when_no_legal_basis(monkeypatch):
    """Proves the old hardcoded-True bug is gone: with no legal_basis supplied
    the flag is honestly False, not a fabricated pass."""
    captured = {}

    async def fake_execute_skill(self, skill, ctx):
        captured.update(ctx)
        return {"status": "SUCCESS_CLEAN", "reasoning_chain": []}

    from app.agents.runtime import AgentExecutor
    monkeypatch.setattr(AgentExecutor, "execute_skill", fake_execute_skill)

    await run_gated_sales_skill(
        skill_id="sales_lead_scoring", steps=[{"step": 1, "prompt": "x"}],
        context={"lead_id": "abc"},
        tenant_id=_t(),
    )
    assert captured["data_processing_basis_logged"] is False


# ── CPQAgent routes through the gated pipeline (SOX-tagged) ────────────────

def _stub_gated_sales(monkeypatch, *, status="SUCCESS_CLEAN", decision=None, **extra):
    calls = {}

    async def fake(skill_id, steps, context, tenant_id, *, compliance_tags=None,
                   confidence=0.85, domain="sales"):
        calls["skill_id"] = skill_id
        calls["compliance_tags"] = compliance_tags
        calls["context"] = context
        if status == "SUCCESS_CLEAN":
            decision_json = decision or {
                "approved": True, "maximum_allowable_discount": 20.0,
                "margin_impact_summary": "Within the 20% enterprise tier.",
                "negotiation_counter": "Approve if multi-year.",
            }
            return {"status": "SUCCESS_CLEAN", "execution_id": "exec-cpq",
                    "reasoning_chain": [{"decision": json.dumps(decision_json)}]}
        return {"status": status, "execution_id": "exec-cpq", **extra}

    monkeypatch.setattr("app.sales.agents.cpq_agent.run_gated_sales_skill", fake)
    return calls


async def test_cpq_agent_routes_through_gated_pipeline_with_sox(db, monkeypatch):
    tenant = _t()
    opp = Opportunity(id=str(uuid.uuid4()), tenant_id=tenant, name="Acme Deal",
                      stage=OpportunityStage.NEGOTIATION, amount=100000.00)
    db.add(opp)
    await db.commit()

    calls = _stub_gated_sales(monkeypatch)
    result = await CPQAgent().evaluate_quote(db, opp.id, 15.0, tenant)

    # It went through the gate pipeline, SOX-tagged, with the deal amount for
    # Gate 6's financial_amount_logged check - not a bare LLM call.
    assert calls["compliance_tags"] == ["SOX"]
    assert calls["context"]["amount"] == 100000.00
    assert result["status"] == "SUCCESS_CLEAN"
    assert result["approved"] is True
    assert result["execution_id"] == "exec-cpq"


async def test_cpq_agent_surfaces_pending_hitl(db, monkeypatch):
    tenant = _t()
    opp = Opportunity(id=str(uuid.uuid4()), tenant_id=tenant, name="Big Deal",
                      stage=OpportunityStage.NEGOTIATION, amount=500000.00)
    db.add(opp)
    await db.commit()

    _stub_gated_sales(monkeypatch, status="PENDING_HITL")
    result = await CPQAgent().evaluate_quote(db, opp.id, 40.0, tenant)
    assert result["status"] == "PENDING_HITL"
    assert "reason" in result


async def test_cpq_agent_surfaces_compliance_block(db, monkeypatch):
    tenant = _t()
    opp = Opportunity(id=str(uuid.uuid4()), tenant_id=tenant, name="Blocked Deal",
                      stage=OpportunityStage.NEGOTIATION, amount=50000.00)
    db.add(opp)
    await db.commit()

    _stub_gated_sales(monkeypatch, status="BLOCKED_COMPLIANCE",
                      violations=[{"framework": "SOX", "reason": "audit fact missing"}])
    result = await CPQAgent().evaluate_quote(db, opp.id, 25.0, tenant)
    assert result["status"] == "BLOCKED_COMPLIANCE"


# ── Real end-to-end proof through the HTTP API + the real gated pipeline ───

async def test_gated_lead_scoring_endpoint_is_not_failed_audit(async_client, db):
    """The CRIT regression test: before the fix, every gated sales agent
    returned {"status": "FAILED_AUDIT"} because data_processing_basis_logged
    was hardcoded True with no real legal_basis to back it. This runs the
    real 7-gate pipeline (no LLM stub) and inspects the response BODY, not
    just the status code - exactly what the pre-existing e2e test failed to
    do (backend/tests/e2e/test_05_sales_department.py only asserted 200)."""
    if not _ollama_reachable():
        pytest.skip("Ollama not reachable at localhost:11434")

    from app.core.database import init_db
    await init_db()

    lead = Lead(id=str(uuid.uuid4()), tenant_id="tenant_acme", company="Acme Test Co",
               contact_name="Jane Test", email="jane@acmetest.com",
               source=LeadSource.WEBSITE, is_converted=False)
    db.add(lead)
    await db.commit()

    r = await async_client.post(f"/api/v1/sales/leads/{lead.id}/score")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("status") != "FAILED_AUDIT", body


# ── GET /sales/commission joins CommissionPlan.plan_name ───────────────────

async def test_commission_list_returns_plan_name_not_raw_id(async_client, db):
    from app.sales.models.commission import CommissionCalculation, CommissionPlan
    from app.sales.models.core import SalesRep

    rep = SalesRep(id=str(uuid.uuid4()), tenant_id="tenant_acme", name="Test Rep",
                   email=f"rep-{uuid.uuid4().hex[:6]}@kaeos.io")
    db.add(rep)
    await db.flush()
    plan = CommissionPlan(id=str(uuid.uuid4()), tenant_id="tenant_acme",
                          plan_name="Test Plan Alpha 2026", rep_id=rep.id)
    db.add(plan)
    await db.flush()
    calc = CommissionCalculation(id=str(uuid.uuid4()), tenant_id="tenant_acme",
                                 plan_id=plan.id, opportunity_id=str(uuid.uuid4()),
                                 deal_value=10000.00, calculated_payout=1000.00)
    db.add(calc)
    await db.commit()

    r = await async_client.get("/api/v1/sales/commission")
    assert r.status_code == 200, r.text
    rows = {row["id"]: row for row in r.json()}
    assert rows[calc.id]["plan_name"] == "Test Plan Alpha 2026"


# ── Seed: idempotency guard + full funnel-stage coverage ───────────────────

async def test_seed_is_idempotent_and_covers_every_funnel_stage(db):
    from app.sales import seed as sales_seed

    tenant = _t()
    ran = await sales_seed.seed_tenant(db, tenant=tenant)
    assert ran is True

    stages = {o.stage for o in (await db.execute(
        select(Opportunity).where(Opportunity.tenant_id == tenant)
    )).scalars().all()}
    assert stages == set(OpportunityStage)  # every stage, incl. both closed outcomes

    # Re-running must not duplicate rows.
    ran_again = await sales_seed.seed_tenant(db, tenant=tenant)
    assert ran_again is False
    count = (await db.execute(
        select(Opportunity).where(Opportunity.tenant_id == tenant)
    )).scalars().all()
    assert len(count) == len(stages)  # unchanged


# ── CCPA/TCPA/DSAR privacy gate: real deterministic call sites ─────────────

async def test_tcpa_gate_blocks_do_not_contact_number(db):
    tenant = _t()
    lead = Lead(id=str(uuid.uuid4()), tenant_id=tenant, company="Blocked Co",
               contact_name="No Call", email="nocall@example.com",
               phone="+15551234567", source=LeadSource.OUTBOUND)
    db.add(lead)
    await db.commit()

    with pytest.raises(PrivacyCheckBlocked):
        await check_contact(db, tenant, lead=lead, channel="sms",
                            do_not_contact=["+15551234567"])


async def test_tcpa_gate_allows_consented_contact(db):
    tenant = _t()
    lead = Lead(id=str(uuid.uuid4()), tenant_id=tenant, company="Clean Co",
               contact_name="Ok Call", email="okcall@example.com",
               phone="+15559999999", source=LeadSource.OUTBOUND)
    db.add(lead)
    await db.commit()

    verdict = await check_contact(db, tenant, lead=lead, channel="sms",
                                  do_not_contact=[], consent=True)
    assert verdict["verified"] is True


async def test_ccpa_gate_blocks_sale_after_optout(db):
    from app.sales.models.accounts import Account

    tenant = _t()
    account = Account(id=str(uuid.uuid4()), tenant_id=tenant, name="Opted Out Corp")
    db.add(account)
    await db.commit()

    with pytest.raises(PrivacyCheckBlocked):
        await check_data_sale(db, tenant, account=account, opted_out_of_sale=True)


async def test_dsar_gate_blocks_past_deadline(db):
    tenant = _t()
    with pytest.raises(PrivacyCheckBlocked):
        await check_dsar(
            db, tenant, subject_type="lead", subject_id="x",
            regime="GDPR", request_date="2026-01-01", fulfilled_date="2026-03-01",
        )


async def test_dsar_gate_passes_within_deadline(db):
    tenant = _t()
    verdict = await check_dsar(
        db, tenant, subject_type="lead", subject_id="x",
        regime="GDPR", request_date="2026-01-01", fulfilled_date="2026-01-20",
    )
    assert verdict["verified"] is True


async def test_privacy_router_endpoints_gate_real_actions(async_client, db):
    lead = Lead(id=str(uuid.uuid4()), tenant_id="tenant_acme", company="Router Co",
               contact_name="Router Test", email="router@example.com",
               phone="+15551234567", source=LeadSource.OUTBOUND)
    from app.sales.models.accounts import Account
    account = Account(id=str(uuid.uuid4()), tenant_id="tenant_acme", name="Router Account Co")
    db.add_all([lead, account])
    await db.commit()

    # TCPA: blocked (number on the do-not-contact list) -> 403 with a verdict.
    r = await async_client.post(f"/api/v1/sales/leads/{lead.id}/contact-check",
                                json={"channel": "sms", "do_not_contact": ["+15551234567"]})
    assert r.status_code == 403, r.text
    assert r.json()["detail"]["verdict"]["blocking"]

    # TCPA: cleared -> 200.
    r = await async_client.post(f"/api/v1/sales/leads/{lead.id}/contact-check",
                                json={"channel": "sms", "do_not_contact": [], "consent": True})
    assert r.status_code == 200, r.text
    assert r.json()["verified"] is True

    # CCPA: opted out -> 403.
    r = await async_client.post(f"/api/v1/sales/accounts/{account.id}/data-sale-check",
                                json={"opted_out_of_sale": True})
    assert r.status_code == 403, r.text

    # DSAR: fulfilled 60 days after a GDPR request (> 1 month) -> 403.
    r = await async_client.post("/api/v1/sales/privacy/dsar-check", json={
        "subject_type": "lead", "subject_id": lead.id, "regime": "GDPR",
        "request_date": "2026-01-01", "fulfilled_date": "2026-03-02",
    })
    assert r.status_code == 403, r.text
