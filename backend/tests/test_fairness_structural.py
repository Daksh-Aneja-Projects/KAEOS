"""
Phase 2C — fairness applicability is STRUCTURAL, not opt-in.

A people-affecting (HCM / protected-class) decision must be fairness-assessed
even when the caller forgets ``requires_fairness_assessment``. The explicit flag
is still honored as an override.
"""
from types import SimpleNamespace

from app.services.fairness_engine import FairnessEngine


def _skill(**kw):
    kw.setdefault("skill_id", "s1")
    kw.setdefault("name", "")
    kw.setdefault("department", "")
    kw.setdefault("tags", [])
    kw.setdefault("compliance_tags", [])
    return SimpleNamespace(**kw)


def test_explicit_flag_still_triggers():
    eng = FairnessEngine()
    assert eng.requires_fairness_check(_skill(), {"requires_fairness_assessment": True}) is True


def test_hr_department_triggers_without_flag():
    eng = FairnessEngine()
    assert eng.requires_fairness_check(_skill(department="hr"), {}) is True


def test_people_impacting_skill_name_triggers():
    eng = FairnessEngine()
    assert eng.requires_fairness_check(_skill(name="Auto termination recommendation"), {}) is True
    assert eng.requires_fairness_check(_skill(skill_id="promotion_ranker"), {}) is True
    assert eng.requires_fairness_check(_skill(tags=["compensation"]), {}) is True


def test_affected_employee_entity_triggers():
    eng = FairnessEngine()
    assert eng.requires_fairness_check(_skill(), {"affected_entity_type": "Employee"}) is True
    assert eng.requires_fairness_check(_skill(), {"affected_entity_type": "Candidate"}) is True


def test_benign_skill_without_signals_does_not_trigger():
    eng = FairnessEngine()
    assert eng.requires_fairness_check(
        _skill(skill_id="invoice_pdf_export", name="Export invoice PDF", department="finance"),
        {},
    ) is False
