"""Legal agents persist their AI decision onto the entity (CRIT #1), and
IPAgent routes through the same governed 7-gate pipeline as every other legal
agent instead of calling the LLM router directly (CRIT #2).

run_gated_legal_skill is stubbed in each agent module so no real Ollama call
happens; extract_decision (the real parser) still runs against the stubbed
reasoning_chain, matching test_ap_agent_match.py / test_sales_gated_agents.py.

IDs are captured into plain strings BEFORE db.expire_all() — re-accessing an
ORM attribute (e.g. `c.id`) on an object AFTER it was expired triggers a sync
lazy-reload outside the async greenlet and raises MissingGreenlet.
"""
import uuid
from datetime import date, timedelta

from sqlalchemy import select

from app.legal.agents.compliance_audit_agent import ComplianceAuditAgent
from app.legal.agents.contract_review_agent import ContractReviewAgent
from app.legal.agents.ip_agent import IPAgent
from app.legal.agents.litigation_agent import LitigationAgent
from app.legal.agents.privacy_dsar_agent import PrivacyDSARAgent
from app.legal.models.compliance import ComplianceObligation, ObligationStatus
from app.legal.models.contracts import Contract, ContractClause, ContractStatus
from app.legal.models.ip import IPStatus, Patent
from app.legal.models.litigation import Case, CaseStage
from app.legal.models.privacy import DataSubjectRequest, DsarStatus, DsarType


def _t():
    return f"tenant_legal_{uuid.uuid4().hex[:6]}"


def _stub(monkeypatch, module_path, decision_json, status="SUCCESS_CLEAN"):
    async def _fake(*args, **kwargs):
        return {
            "status": status,
            "execution_id": "exec-test",
            "reasoning_chain": [{"decision": decision_json}],
        }
    monkeypatch.setattr(f"{module_path}.run_gated_legal_skill", _fake)
    return _fake


# ── ContractReviewAgent ─────────────────────────────────────────────────────

async def test_contract_review_persists_risk_score_and_summary(db, monkeypatch):
    tenant = _t()
    contract_id = str(uuid.uuid4())
    db.add(Contract(id=contract_id, tenant_id=tenant, title="MSA", counterparty="Acme",
                    contract_type="MSA", status=ContractStatus.IN_REVIEW))
    await db.commit()

    _stub(monkeypatch, "app.legal.agents.contract_review_agent",
          '{"risk_score": 62.5, "high_risk_clauses": ["Indemnification"], "recommendation": "Cap liability."}')

    result = await ContractReviewAgent().review_contract(db, contract_id, tenant)
    assert result["status"] == "success"

    db.expire_all()
    row = (await db.execute(select(Contract).where(Contract.id == contract_id))).scalar_one()
    assert float(row.ai_risk_score) == 62.5
    assert "Indemnification" in row.ai_summary
    assert "Cap liability." in row.ai_summary


async def test_contract_review_never_fabricates_missing_risk_score(db, monkeypatch):
    """A decision that omits risk_score must not clobber the prior value with 0."""
    tenant = _t()
    contract_id = str(uuid.uuid4())
    db.add(Contract(id=contract_id, tenant_id=tenant, title="NDA", counterparty="Beta",
                    contract_type="NDA", status=ContractStatus.IN_REVIEW, ai_risk_score=15.0))
    await db.commit()

    _stub(monkeypatch, "app.legal.agents.contract_review_agent", '{"recommendation": "Looks fine."}')

    await ContractReviewAgent().review_contract(db, contract_id, tenant)

    db.expire_all()
    row = (await db.execute(select(Contract).where(Contract.id == contract_id))).scalar_one()
    assert float(row.ai_risk_score) == 15.0  # untouched, never zeroed


async def test_contract_review_wires_contract_clause_checker_context(db, monkeypatch):
    """CONTRACT_CLAUSE (app/compliance/checkers/legal.py) needs
    context['contract'] = {type, clauses}; assert it is populated from the
    contract's real clause inventory, and the tag is actually passed."""
    tenant = _t()
    contract_id = str(uuid.uuid4())
    db.add(Contract(id=contract_id, tenant_id=tenant, title="NDA", counterparty="Gamma",
                    contract_type="NDA", status=ContractStatus.IN_REVIEW))
    await db.flush()
    db.add(ContractClause(id=str(uuid.uuid4()), tenant_id=tenant, contract_id=contract_id,
                          clause_type="Confidentiality", original_text="..."))
    await db.commit()

    captured = {}

    async def _fake(*args, **kwargs):
        captured["context"] = kwargs.get("context") or {}
        captured["compliance_tags"] = kwargs.get("compliance_tags")
        return {"status": "SUCCESS_CLEAN", "reasoning_chain": [{"decision": "{}"}]}

    monkeypatch.setattr("app.legal.agents.contract_review_agent.run_gated_legal_skill", _fake)

    await ContractReviewAgent().review_contract(db, contract_id, tenant)

    assert "CONTRACT_CLAUSE" in captured["compliance_tags"]
    assert captured["context"]["contract"] == {"type": "NDA", "clauses": ["Confidentiality"]}


# ── ComplianceAuditAgent ─────────────────────────────────────────────────────

async def test_compliance_audit_completes_obligation_when_compliant_true(db, monkeypatch):
    tenant = _t()
    ob_id = str(uuid.uuid4())
    db.add(ComplianceObligation(id=ob_id, tenant_id=tenant, title="SOC2 Review",
                               status=ObligationStatus.PENDING))
    await db.commit()

    _stub(monkeypatch, "app.legal.agents.compliance_audit_agent",
          '{"compliant": true, "gaps": [], "remediation": "", "risk_level": "LOW"}')

    result = await ComplianceAuditAgent().audit_obligation(db, ob_id, tenant)
    assert result["status"] == "SUCCESS_CLEAN"

    db.expire_all()
    row = (await db.execute(select(ComplianceObligation).where(ComplianceObligation.id == ob_id))).scalar_one()
    assert row.status == ObligationStatus.COMPLETED


async def test_compliance_audit_leaves_status_when_not_compliant(db, monkeypatch):
    tenant = _t()
    ob_id = str(uuid.uuid4())
    db.add(ComplianceObligation(id=ob_id, tenant_id=tenant, title="SOC2 Review",
                               status=ObligationStatus.OVERDUE))
    await db.commit()

    _stub(monkeypatch, "app.legal.agents.compliance_audit_agent",
          '{"compliant": false, "gaps": ["missing evidence"], "remediation": "collect logs", "risk_level": "HIGH"}')

    await ComplianceAuditAgent().audit_obligation(db, ob_id, tenant)

    db.expire_all()
    row = (await db.execute(select(ComplianceObligation).where(ComplianceObligation.id == ob_id))).scalar_one()
    assert row.status == ObligationStatus.OVERDUE  # never fabricated to COMPLETED


# ── LitigationAgent ──────────────────────────────────────────────────────────

async def test_litigation_agent_persists_outcome(db, monkeypatch):
    tenant = _t()
    case_id = str(uuid.uuid4())
    db.add(Case(id=case_id, tenant_id=tenant, case_name="X v. Y",
               stage=CaseStage.DISCOVERY, opposing_party="Y Corp"))
    await db.commit()

    _stub(monkeypatch, "app.legal.agents.litigation_agent",
          '{"case_strength": "MODERATE", "risk_score": 55, "settle_or_fight": "SETTLE", '
          '"rationale": "Exposure exceeds litigation cost."}')

    result = await LitigationAgent().evaluate_case(db, case_id, tenant)
    assert result["status"] == "success"

    db.expire_all()
    row = (await db.execute(select(Case).where(Case.id == case_id))).scalar_one()
    assert "MODERATE" in row.outcome
    assert "SETTLE" in row.outcome
    assert "Exposure exceeds litigation cost." in row.outcome


async def test_litigation_agent_pending_hitl_leaves_outcome_untouched(db, monkeypatch):
    tenant = _t()
    case_id = str(uuid.uuid4())
    db.add(Case(id=case_id, tenant_id=tenant, case_name="P v. Q",
               stage=CaseStage.PLEADING, opposing_party="Q Corp", outcome="Prior outcome text."))
    await db.commit()

    async def _pending(*args, **kwargs):
        return {"status": "PENDING_HITL", "execution_id": "exec-hitl"}
    monkeypatch.setattr("app.legal.agents.litigation_agent.run_gated_legal_skill", _pending)

    result = await LitigationAgent().evaluate_case(db, case_id, tenant)
    assert result["status"] == "PENDING_HITL"

    db.expire_all()
    row = (await db.execute(select(Case).where(Case.id == case_id))).scalar_one()
    assert row.outcome == "Prior outcome text."


# ── PrivacyDSARAgent ─────────────────────────────────────────────────────────

async def test_privacy_dsar_agent_marks_validated_and_advances_status(db, monkeypatch):
    tenant = _t()
    dsar_id = str(uuid.uuid4())
    db.add(DataSubjectRequest(id=dsar_id, tenant_id=tenant, requestor_name="A",
                              requestor_email="a@example.com", request_type=DsarType.ACCESS,
                              status=DsarStatus.RECEIVED, request_date=date.today(),
                              deadline_date=date.today() + timedelta(days=30), ai_validation=False))
    await db.commit()

    _stub(monkeypatch, "app.legal.agents.privacy_dsar_agent",
          '{"response_plan": "Export account records.", "systems_to_query": ["crm"], "deadline_risk": "LOW"}')

    result = await PrivacyDSARAgent().process_dsar(db, dsar_id, tenant)
    assert result["status"] == "success"

    db.expire_all()
    row = (await db.execute(select(DataSubjectRequest).where(DataSubjectRequest.id == dsar_id))).scalar_one()
    assert row.ai_validation is True
    assert row.status == DsarStatus.PROCESSING


async def test_privacy_dsar_agent_never_regresses_completed_status(db, monkeypatch):
    tenant = _t()
    dsar_id = str(uuid.uuid4())
    db.add(DataSubjectRequest(id=dsar_id, tenant_id=tenant, requestor_name="B",
                              requestor_email="b@example.com", request_type=DsarType.ACCESS,
                              status=DsarStatus.COMPLETED, request_date=date.today() - timedelta(days=20),
                              deadline_date=date.today() + timedelta(days=10), ai_validation=True))
    await db.commit()

    _stub(monkeypatch, "app.legal.agents.privacy_dsar_agent",
          '{"response_plan": "Re-export.", "systems_to_query": [], "deadline_risk": "LOW"}')

    await PrivacyDSARAgent().process_dsar(db, dsar_id, tenant)

    db.expire_all()
    row = (await db.execute(select(DataSubjectRequest).where(DataSubjectRequest.id == dsar_id))).scalar_one()
    assert row.status == DsarStatus.COMPLETED  # never regressed


# ── IPAgent (CRIT #2: governed pipeline, not a bare router call) ────────────

async def test_ip_agent_routes_through_gated_pipeline_not_bare_router(db, monkeypatch):
    tenant = _t()
    patent_id = str(uuid.uuid4())
    db.add(Patent(id=patent_id, tenant_id=tenant, title="Widget Patent",
                 status=IPStatus.PENDING, inventors="A. Inventor", abstract="A novel widget."))
    await db.commit()

    called = {}

    async def _fake_gated(*args, **kwargs):
        called["used"] = True
        return {"status": "SUCCESS_CLEAN", "reasoning_chain": [
            {"decision": '{"is_novel": true, "confidence_score": 0.9, '
                         '"prior_art_found": [], "recommendation": "File."}'}
        ]}

    async def _fail_if_called(*args, **kwargs):
        raise AssertionError("evaluate_patentability must not call LLMRouter.complete directly")

    monkeypatch.setattr("app.legal.agents.ip_agent.run_gated_legal_skill", _fake_gated)
    # Guard against a regression back to the bare router call.
    from app.services.llm_router import LLMRouter
    monkeypatch.setattr(LLMRouter, "complete", _fail_if_called)

    result = await IPAgent().evaluate_patentability(db, patent_id, tenant)
    assert called.get("used") is True
    assert result["status"] == "success"

    db.expire_all()
    row = (await db.execute(select(Patent).where(Patent.id == patent_id))).scalar_one()
    assert row.status == IPStatus.ACTIVE


async def test_ip_agent_pending_hitl_does_not_mutate_patent(db, monkeypatch):
    tenant = _t()
    patent_id = str(uuid.uuid4())
    db.add(Patent(id=patent_id, tenant_id=tenant, title="Gadget Patent",
                 status=IPStatus.PENDING, inventors="B. Inventor", abstract="A novel gadget."))
    await db.commit()

    async def _fake_pending(*args, **kwargs):
        return {"status": "PENDING_HITL", "execution_id": "exec-hitl"}
    monkeypatch.setattr("app.legal.agents.ip_agent.run_gated_legal_skill", _fake_pending)

    result = await IPAgent().evaluate_patentability(db, patent_id, tenant)
    assert result["status"] == "PENDING_HITL"

    db.expire_all()
    row = (await db.execute(select(Patent).where(Patent.id == patent_id))).scalar_one()
    assert row.status == IPStatus.PENDING  # untouched until a human clears the gate


async def test_ip_agent_abandons_only_on_explicit_negative(db, monkeypatch):
    tenant = _t()
    patent_id = str(uuid.uuid4())
    db.add(Patent(id=patent_id, tenant_id=tenant, title="Gizmo Patent",
                 status=IPStatus.PENDING, inventors="C. Inventor", abstract="An obvious gizmo."))
    await db.commit()

    _stub(monkeypatch, "app.legal.agents.ip_agent",
          '{"is_novel": false, "confidence_score": 0.8, "prior_art_found": ["US1234567"], '
          '"recommendation": "Abandon."}')

    await IPAgent().evaluate_patentability(db, patent_id, tenant)

    db.expire_all()
    row = (await db.execute(select(Patent).where(Patent.id == patent_id))).scalar_one()
    assert row.status == IPStatus.ABANDONED


async def test_ip_agent_keeps_status_when_novelty_is_ambiguous(db, monkeypatch):
    """A response that omits is_novel must never silently kill a filing."""
    tenant = _t()
    patent_id = str(uuid.uuid4())
    db.add(Patent(id=patent_id, tenant_id=tenant, title="Ambiguous Patent",
                 status=IPStatus.PENDING, inventors="D. Inventor", abstract="Unclear novelty."))
    await db.commit()

    _stub(monkeypatch, "app.legal.agents.ip_agent",
          '{"confidence_score": 0.4, "prior_art_found": [], "recommendation": "Needs more research."}')

    await IPAgent().evaluate_patentability(db, patent_id, tenant)

    db.expire_all()
    row = (await db.execute(select(Patent).where(Patent.id == patent_id))).scalar_one()
    assert row.status == IPStatus.PENDING  # left under review, not fabricated
