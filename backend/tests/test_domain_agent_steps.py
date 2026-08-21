"""Non-HR agents get department-specific steps, not a generic assess/act template."""
from types import SimpleNamespace

from app.workforce.orchestration.workforce_generator import build_agent_skill


def _cap(name="task"):
    return SimpleNamespace(name=name, compliance_tags=[])


def _ids(pack, agent_type="unmapped_agent", cap="task"):
    skill = build_agent_skill({"type": agent_type, "name": "Agent", "description": "does work"}, pack, _cap(cap))
    return [s["id"] for s in skill["steps"]]


def test_finance_gets_ledger_steps():
    ids = _ids("finance", cap="invoice_processing")
    assert ids == ["load_ledger", "analyze", "post"]


def test_legal_gets_matter_review_steps():
    ids = _ids("legal", cap="contract_review")
    assert "load_matter" in ids and "review" in ids and "recommend" in ids


def test_sales_support_operations_have_domain_steps():
    assert "load_opp" in _ids("sales")
    assert "load_ticket" in _ids("support")
    assert "load_context" in _ids("operations")


# H15: the four previously-uncovered departments (the HIPAA/ECOA/SOC2/OFAC ones)
# must get real domain-grounded steps, not the generic assess/act fallback.
def test_engineering_healthcare_lending_procurement_have_domain_steps():
    assert _ids("engineering")[0] == "load_change"
    assert _ids("healthcare")[0] == "load_case"
    assert _ids("lending")[0] == "load_application"
    assert _ids("procurement")[0] == "load_po"


def test_every_canonical_department_beats_the_generic_fallback():
    """Regression lock over the whole roster: no governed department may fall
    through to the two-step generic template."""
    from app.core.domain_seed import DEPARTMENT_SLUGS
    generic = ["assess", "act"]
    for slug in DEPARTMENT_SLUGS:
        steps = _ids(slug)
        assert steps != generic, f"{slug} fell through to the generic assess/act template"
        assert len(steps) >= 2


def test_unknown_domain_falls_back_to_generic_but_real():
    assert _ids("mystery_domain") == ["assess", "act"]


def test_hr_still_uses_its_per_agent_steps():
    ids = _ids("hr", agent_type="recruiting")
    assert "screen_candidate" in ids   # HR-specific, not the generic fallback
