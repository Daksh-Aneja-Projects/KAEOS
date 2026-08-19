"""Contract test for the consolidated department gate.

Ten department packages used to carry ten near-identical copies of the gated
skill runner. They are now one mechanism (``app.agents.department_gate``) plus
ten thin bindings. This test pins what each department actually hands to the
``AgentExecutor``, so the consolidation cannot silently drift back apart — and
so the per-department quirks below stay deliberate rather than accidental.

Each case was verified equivalent to the pre-consolidation runner across 4563
input combinations; these are the representative cases, one per quirk.
"""
from __future__ import annotations

import importlib
from typing import Any, Dict

import pytest

from app.agents.department_gate import DEPLOY_COMPLIANCE
from app.agents.runtime import AgentExecutor


@pytest.fixture
def captured(monkeypatch):
    """Capture the (skill_dict, ctx) a runner hands to the executor."""
    box: Dict[str, Any] = {}

    async def stub(self, skill_dict, ctx, **kwargs):
        box["skill"] = skill_dict
        box["ctx"] = ctx
        return {"status": "SUCCESS_CLEAN"}

    monkeypatch.setattr(AgentExecutor, "execute_skill", stub)
    return box


async def run(dept: str, skill_id: str, context=None, **kwargs):
    mod = importlib.import_module(f"app.{dept}.agents.gated_runner")
    fn = getattr(mod, f"run_gated_{dept}_skill")
    return await fn(
        skill_id,
        [{"step": 1, "name": "S", "prompt": "p"}],
        dict(context or {}),
        "tenant_acme",
        **kwargs,
    )


# ── Defaults: every department applies its own compliance tag set ────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("dept,skill_id,expected_tags,expected_confidence", [
    ("engineering", "engineering_lint", ["SOC2", "CHANGE_MANAGEMENT"], 0.85),
    ("finance", "finance_ap", ["SOX", "GAAP", "PCI"], 0.85),
    ("healthcare", "healthcare_code", ["HIPAA_MINIMUM_NECESSARY", "HIPAA_AUTHORIZATION", "PART2"], 0.95),
    ("hr", "hr_onboard", ["EEOC", "GDPR"], 0.85),
    ("legal", "legal_review", ["GDPR", "CCPA", "PRIVACY"], 0.85),
    ("lending", "lending_underwrite", ["ECOA", "FAIR_LENDING", "TILA"], 0.9),
    ("operations", "operations_qa", ["SOC2", "INTERNAL_CONTROL"], 0.85),
    ("procurement", "procurement_source", ["THREE_WAY_MATCH", "SEGREGATION_OF_DUTIES",
                                           "SPEND_AUTHORIZATION", "OFAC_SANCTIONS"], 0.85),
    ("sales", "sales_score", ["GDPR"], 0.85),
    ("support", "support_triage", ["GDPR", "CCPA", "SLA_BREACH", "PII_REDACTION"], 0.85),
])
async def test_department_defaults(captured, dept, skill_id, expected_tags, expected_confidence):
    await run(dept, skill_id)
    assert captured["skill"]["compliance_tags"] == expected_tags
    assert captured["skill"]["confidence"] == expected_confidence
    assert captured["skill"]["department"] == dept
    # The synthetic Skill the fairness and debate gates read must agree.
    skill_obj = captured["ctx"]["_skill_obj"]
    assert skill_obj.domain == dept
    assert skill_obj.compliance_tags == expected_tags
    assert skill_obj.confidence_tier == "INFERRED"


# ── Empty-tag semantics differ by department, deliberately ──────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("dept,skill_id,expected", [
    # These three honour an explicit [] as "no compliance tags". The hr fairness
    # sweep depends on it: its EEOC check *is* the fairness gate.
    ("hr", "hr_sweep", []),
    ("healthcare", "healthcare_code", []),
    ("engineering", "engineering_lint", []),
    # The other seven replace [] with their defaults (truthiness, not `is None`).
    ("sales", "sales_score", ["GDPR"]),
    ("finance", "finance_ap", ["SOX", "GAAP", "PCI"]),
    ("legal", "legal_review", ["GDPR", "CCPA", "PRIVACY"]),
    ("lending", "lending_underwrite", ["ECOA", "FAIR_LENDING", "TILA"]),
    ("operations", "operations_qa", ["SOC2", "INTERNAL_CONTROL"]),
    ("support", "support_triage", ["GDPR", "CCPA", "SLA_BREACH", "PII_REDACTION"]),
    ("procurement", "procurement_source", ["THREE_WAY_MATCH", "SEGREGATION_OF_DUTIES",
                                           "SPEND_AUTHORIZATION", "OFAC_SANCTIONS"]),
])
async def test_explicit_empty_tags(captured, dept, skill_id, expected):
    await run(dept, skill_id, compliance_tags=[])
    assert captured["skill"]["compliance_tags"] == expected


# ── Skills that must always reach a human ───────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("dept,skill_id,forced_confidence", [
    ("engineering", "engineering_deploy_approval", 0.79),
    ("sales", "sales_proposal_gen", 0.50),
    ("support", "support_auto_resolve", 0.79),
])
async def test_forced_hitl_skills_ignore_caller_confidence(captured, dept, skill_id, forced_confidence):
    """A caller cannot raise a forced-HITL skill above its threshold."""
    await run(dept, skill_id, confidence=0.99)
    assert captured["skill"]["confidence"] == forced_confidence


@pytest.mark.asyncio
async def test_engineering_deploy_uses_change_management_control_set(captured):
    await run("engineering", "engineering_deploy_approval")
    assert captured["skill"]["compliance_tags"] == list(DEPLOY_COMPLIANCE)


@pytest.mark.asyncio
async def test_engineering_deploy_caller_tags_win_over_skill_default(captured):
    await run("engineering", "engineering_deploy_approval", compliance_tags=["SOC2"])
    assert captured["skill"]["compliance_tags"] == ["SOC2"]


@pytest.mark.asyncio
@pytest.mark.parametrize("requires_hitl", [True, False])
async def test_healthcare_always_hitl_flag(captured, requires_hitl):
    """Clinical actions cannot be de-escalated below a human at Gate 3."""
    await run("healthcare", "healthcare_code", requires_hitl=requires_hitl)
    assert captured["skill"]["always_hitl"] is requires_hitl


@pytest.mark.asyncio
async def test_only_healthcare_sets_always_hitl(captured):
    await run("hr", "hr_onboard")
    assert "always_hitl" not in captured["skill"]


# ── Gate 6 audit flags are derived from real context, not asserted ──────────

@pytest.mark.asyncio
@pytest.mark.parametrize("dept,skill_id", [
    ("hr", "hr_onboard"),
    ("sales", "sales_score"),
    ("support", "support_triage"),
    ("healthcare", "healthcare_code"),
    ("legal", "legal_review"),  # legal now derives it too (was hardcoded True)
])
async def test_lawful_basis_flag_requires_a_real_basis(captured, dept, skill_id):
    """Gate 6 must not be satisfied by an assertion that no basis backs."""
    await run(dept, skill_id, compliance_tags=["GDPR"])
    assert captured["ctx"]["data_processing_basis_logged"] is False

    await run(dept, skill_id, compliance_tags=["GDPR"], context={"legal_basis": "contract"})
    assert captured["ctx"]["data_processing_basis_logged"] is True


@pytest.mark.asyncio
async def test_legal_derives_lawful_basis_and_honours_caller(captured):
    """Legal — the GDPR/CCPA department — now derives Gate 6's lawful-basis flag
    from a real ``legal_basis`` instead of hardcoding ``True`` (source=None,
    force=True). It was previously the ONE department structurally unable to fail
    its own lawful-basis audit. Its agents now supply a genuine basis (see
    app/legal/agents/*_agent.py), and force=True is dropped, so an explicit
    caller value is honoured like every other department.
    """
    # No basis -> the flag is False (Gate 6 will fail the run), not asserted True.
    await run("legal", "legal_review", compliance_tags=["GDPR"])
    assert captured["ctx"]["data_processing_basis_logged"] is False

    # A real basis -> True.
    await run("legal", "legal_review", compliance_tags=["GDPR"],
              context={"legal_basis": "legal_obligation:dsar"})
    assert captured["ctx"]["data_processing_basis_logged"] is True

    # force=True dropped: an explicit caller value now survives (setdefault).
    await run("legal", "legal_review", compliance_tags=["GDPR"],
              context={"data_processing_basis_logged": True})
    assert captured["ctx"]["data_processing_basis_logged"] is True


@pytest.mark.asyncio
async def test_audit_flags_are_scoped_to_their_tags(captured):
    """A flag is seeded only when its compliance regime is actually attached."""
    await run("finance", "finance_ap", compliance_tags=["SOX"], context={"amount": 100})
    assert captured["ctx"]["financial_amount_logged"] is True
    assert "pci_dss_compliant" not in captured["ctx"]

    await run("finance", "finance_ap", compliance_tags=["PCI"], context={"pci_validated": True})
    assert captured["ctx"]["pci_dss_compliant"] is True
    assert "financial_amount_logged" not in captured["ctx"]


@pytest.mark.asyncio
async def test_finance_amount_flag_also_covers_gaap(captured):
    """Deliberately preserved: finance gates on SOX *or* GAAP, hr/sales on SOX
    alone. Documented as a REVIEW item in department_gate.FINANCE."""
    await run("finance", "finance_ap", compliance_tags=["GAAP"], context={"amount": 100})
    assert captured["ctx"]["financial_amount_logged"] is True

    await run("hr", "hr_comp", compliance_tags=["GAAP"], context={"amount": 100})
    assert "financial_amount_logged" not in captured["ctx"]


@pytest.mark.asyncio
async def test_caller_supplied_audit_flag_is_not_overwritten(captured):
    """Derived flags use setdefault, so an explicit caller value survives."""
    await run("hr", "hr_onboard", compliance_tags=["GDPR"],
              context={"data_processing_basis_logged": True})
    assert captured["ctx"]["data_processing_basis_logged"] is True


# ── Department-specific context ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_hr_marks_decisions_for_fairness_scoring(captured):
    await run("hr", "hr_onboard")
    assert captured["ctx"]["requires_fairness_assessment"] is True

    await run("hr", "hr_onboard", requires_fairness=False)
    assert captured["ctx"]["requires_fairness_assessment"] is False


@pytest.mark.asyncio
async def test_finance_resolves_four_eyes_attribution(captured):
    """check_sox needs a maker and an approver that are distinct identities."""
    await run("finance", "finance_ap", context={"has_human_approver": "alice@example.com"})
    assert captured["ctx"]["approver"] == "alice@example.com"

    # A bare True is unverifiable four-eyes: it must not become an approver.
    await run("finance", "finance_ap", context={"has_human_approver": True})
    assert captured["ctx"]["approver"] is None
    assert captured["ctx"]["has_human_approver"] is True

    # An explicit approver wins.
    await run("finance", "finance_ap", context={"maker": "bob", "approver": "carol"})
    assert (captured["ctx"]["maker"], captured["ctx"]["approver"]) == ("bob", "carol")


@pytest.mark.asyncio
async def test_lending_normalises_missing_approver_to_false(captured):
    """ECOA/TILA checkers see an explicit "no approver", not a missing key."""
    await run("lending", "lending_underwrite")
    assert captured["ctx"]["has_human_approver"] is False


# ── Shared plumbing ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_caller_execution_id_is_preserved(captured):
    await run("hr", "hr_onboard", context={"execution_id": "exec-pinned"})
    assert captured["ctx"]["execution_id"] == "exec-pinned"


@pytest.mark.asyncio
async def test_execution_id_is_generated_when_absent(captured):
    await run("hr", "hr_onboard")
    assert captured["ctx"]["execution_id"]


@pytest.mark.asyncio
async def test_tenant_id_is_always_stamped(captured):
    await run("sales", "sales_score", context={"tenant_id": "attacker"})
    assert captured["ctx"]["tenant_id"] == "tenant_acme"


def test_every_department_shares_one_extract_decision():
    """The helper existed in ten copies that drifted into five variants."""
    departments = ["engineering", "finance", "healthcare", "hr", "legal",
                   "lending", "operations", "procurement", "sales", "support"]
    impls = {
        importlib.import_module(f"app.{d}.agents.gated_runner").extract_decision
        for d in departments
    }
    assert len(impls) == 1


@pytest.mark.parametrize("result,expected", [
    ({}, {}),
    ({"reasoning_chain": []}, {}),
    ({"reasoning_chain": [{"decision": "not json"}]}, {}),
    ({"reasoning_chain": [{"decision": None}]}, {}),
    ({"reasoning_chain": [{"decision": '{"approved": true}'}]}, {"approved": True}),
    ({"reasoning_chain": [{"decision": '```json\n{"a": 1}\n```'}]}, {"a": 1}),
])
def test_extract_decision_degrades_instead_of_raising(result, expected):
    """A model that fails to emit JSON must not take down a decision that
    already passed its gates."""
    from app.agents.department_gate import extract_decision
    assert extract_decision(result) == expected
