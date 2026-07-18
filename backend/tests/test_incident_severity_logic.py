"""
Unit tests for incident severity resolution — the one-way floor.

Regression guard for a bug found by running the agent over REAL ServiceNow data:
a recorded SEV1 with a null affected_users field was silently downgraded to SEV2
because the resolver re-derived severity from scratch. Triage must be able to
ESCALATE severity but never silently de-escalate a recorded value.
"""

from app.engineering.agents.incident_agent import IncidentAgent
from app.engineering.models.incidents import IncidentSeverity as S

R = IncidentAgent._resolve_severity


def test_recorded_sev1_survives_null_impact_fields():
    # The exact real-data failure: SEV1 recorded, user count unknown.
    assert R(None, {"recorded_severity": "SEV1", "customer_impacting": True, "affected_users": None}) == S.SEV1


def test_model_may_not_downgrade_recorded_severity():
    assert R("SEV3", {"recorded_severity": "SEV1", "customer_impacting": True}) == S.SEV1
    assert R("SEV4", {"recorded_severity": "SEV2"}) == S.SEV2


def test_model_may_escalate():
    assert R("SEV1", {"recorded_severity": "SEV3", "customer_impacting": False}) == S.SEV1


def test_large_user_impact_escalates_to_sev1():
    assert R(None, {"customer_impacting": True, "affected_users": 5000}) == S.SEV1


def test_tier1_service_escalates():
    # A tier-1 service should not sit at SEV3/SEV4 by default.
    assert R(None, {"customer_impacting": False, "service_tier": "TIER_1"}) in (S.SEV1, S.SEV2)


def test_spent_error_budget_escalates():
    base = R(None, {"customer_impacting": True, "affected_users": 100})
    hot = R(None, {"customer_impacting": True, "affected_users": 100, "error_budget_remaining_pct": 5})
    assert IncidentAgent._SEV_RANK[hot] <= IncidentAgent._SEV_RANK[base]


def test_no_impact_no_record_defaults_sev3():
    assert R(None, {"customer_impacting": False}) == S.SEV3
